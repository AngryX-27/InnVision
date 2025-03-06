"""
aggregator_service/logic/orders.py

Расширенный модуль по работе с заказами (Orders), включая:
1. Создание/обновление заказов в БД
2. Система статусов с гибкой проверкой переходов
3. Общение с Orchestrator (с ретраями и fallback)
4. Интеграция с GPT
5. Ведение диалогов в client_dialogs
6. Расширенное логгирование (пример со structlog)
7. Поддержка fallback-очереди (failed_orders) и переобработки
8. Пример асинхронного подхода/диспетчеризации (при желании)
9. Пример Celery-подхода (комментариями)

Внимание: Для brevity часть кода демонстрационная (например, fetch_jobs из upwork_client),
нужно адаптировать под ваши реальные методы и модели.
"""

from enum import Enum
import time
import requests
import uuid

from datetime import datetime
from typing import Any, Dict, Optional, List

# Пример использования structlog для логирования
import structlog

from aggregator_service.db import SessionLocal
from aggregator_service.aggregator_db.models import (
    Order,
    ClientDialog,
    FailedOrder
)
from aggregator_service.config.config import (
    ORCHESTRATOR_URL,
    MAIN_INTERVAL,
    MAX_RETRIES,
    RETRY_DELAY,
    logger,  # Если хотите оставить совместное использование стандартного logger
    # Ниже - то, что вы можете вынести в config:
    # CELERY_ENABLED, USE_STRUCTLOG, и т. п.
)

###############################################################################
# Пример инициализации structlog (можно вынести в отдельный config-инициализатор)
###############################################################################
# Ниже — пример, как инициализировать structlog:
# structlog.configure(
#     processors=[
#         structlog.processors.TimeStamper(fmt="iso"),
#         structlog.dev.ConsoleRenderer()  # Или JSON-рендерер (structlog.processors.JSONRenderer())
#     ],
#     wrapper_class=structlog.make_filtering_bound_logger(min_level="INFO"),
#     context_class=dict,
#     cache_logger_on_first_use=True,
# )
#
# logger = structlog.get_logger(__name__)

# Для примера будем использовать уже существующий logger,
# и при желании — structlog на отдельных этапах
slog = structlog.get_logger(__name__)

###############################################################################
# СТАТУСЫ и ЛОГИКА ПЕРЕХОДОВ
###############################################################################


class OrderStatus(str, Enum):
    NEW = "new"
    NEGOTIATION = "negotiation"
    AGREED = "agreed"
    IN_PROGRESS = "in_progress"
    DONE = "done"
    CLOSED = "closed"
    FAILED = "failed"
    CANCELED = "canceled"  # Доп. статус при отмене клиентом (пример)


# Позволяем расширять
VALID_STATUSES = [st.value for st in OrderStatus]

# Более гибкая таблица допустимых переходов.
# Если статус не упомянут в ALLOWED_TRANSITIONS,
# значит никаких переходов из него дальше не делаем.
ALLOWED_TRANSITIONS = {
    OrderStatus.NEW: [OrderStatus.NEGOTIATION, OrderStatus.AGREED, OrderStatus.FAILED, OrderStatus.CANCELED],
    OrderStatus.NEGOTIATION: [OrderStatus.AGREED, OrderStatus.FAILED, OrderStatus.CANCELED],
    OrderStatus.AGREED: [OrderStatus.IN_PROGRESS, OrderStatus.FAILED, OrderStatus.CANCELED],
    OrderStatus.IN_PROGRESS: [OrderStatus.DONE, OrderStatus.FAILED, OrderStatus.CANCELED],
    OrderStatus.DONE: [OrderStatus.CLOSED, OrderStatus.FAILED],
    OrderStatus.CLOSED: [],
    OrderStatus.FAILED: [],
    OrderStatus.CANCELED: []
}


###############################################################################
# УТИЛИТЫ РАБОТЫ С БД (CRUD + client_dialogs + fallback)
###############################################################################
def record_order(
    session,
    topic: str,
    language: str,
    client_name: str = None,
    price: float = None,
    is_urgent: bool = False,
    external_client_id: str = None,
    job_id: str = None,
    initial_status: OrderStatus = OrderStatus.NEW
) -> int:
    """
    Создаёт новый Order в БД, возвращает его ID.
    Поля external_client_id (UpWork) и job_id (уникальный ID на бирже) 
    помогают предотвращать дубли и проверять связь с внешним клиентом.
    """
    new_order = Order(
        topic=topic,
        language=language,
        status=initial_status.value,
        client_name=client_name,
        price=price,
        is_urgent=is_urgent,
        external_client_id=external_client_id,
        job_id=job_id
    )
    session.add(new_order)
    session.commit()
    session.refresh(new_order)
    slog.info(
        "order_created",
        order_id=new_order.id,
        topic=topic,
        language=language,
        external_client_id=external_client_id,
        job_id=job_id
    )
    return new_order.id


def update_order_status(
    session,
    order_id: int,
    new_status: OrderStatus,
    reason: Optional[str] = None
) -> None:
    """
    Обновляет статус заказа в БД, с валидацией допустимого перехода 
    по ALLOWED_TRANSITIONS. Опционально указывает reason (причину, если FAILED/CANCELED).
    """
    order_obj = session.get(Order, order_id)
    if not order_obj:
        slog.warning("order_not_found", order_id=order_id)
        return

    old_status = order_obj.status
    old_status_enum = OrderStatus(
        old_status) if old_status in VALID_STATUSES else None

    if not old_status_enum:
        slog.warning("invalid_old_status", order_id=order_id,
                     old_status=old_status)
        return

    if new_status.value not in VALID_STATUSES:
        slog.warning("invalid_new_status", order_id=order_id,
                     new_status=new_status.value)
        return

    possible_transitions = ALLOWED_TRANSITIONS.get(old_status_enum, [])
    if new_status not in possible_transitions:
        slog.warning(
            "invalid_status_transition",
            order_id=order_id,
            old_status=old_status,
            attempted_status=new_status.value
        )
        return

    order_obj.status = new_status.value
    # Если статус проблемный, можем записать причину.
    if reason and new_status in [OrderStatus.FAILED, OrderStatus.CANCELED]:
        # В модели Order можно предусмотреть поле reason.
        if hasattr(order_obj, "reason"):
            order_obj.reason = reason

    session.commit()
    slog.info(
        "order_status_updated",
        order_id=order_id,
        old_status=old_status,
        new_status=new_status.value,
        reason=reason
    )


def add_dialog_message(
    session,
    order_id: int,
    role: str,
    message: str,
    msg_type: str = "text"
) -> None:
    """
    Добавляет сообщение в client_dialogs, привязывая к конкретному order_id.
    role может быть: "user", "assistant", "system", "aggregator" и т.д.
    msg_type: "text", "file", "link", ...
    """
    dialog = ClientDialog(
        order_id=order_id,
        role=role,
        message=message,
        message_type=msg_type
    )
    session.add(dialog)
    session.commit()
    slog.debug(
        "dialog_message_added",
        order_id=order_id,
        role=role,
        # ограничимся первыми 30 символами для лога
        message_preview=message[:30]
    )


def get_dialog_messages(
    session,
    order_id: int
) -> List[Dict[str, str]]:
    """
    Возвращает все сообщения по заказу в виде списка dict {role, content}.
    Упорядочено по возрастанию ID, т.е. в хронологическом порядке.
    """
    rows = (
        session.query(ClientDialog)
        .filter(ClientDialog.order_id == order_id)
        .order_by(ClientDialog.id.asc())
        .all()
    )
    return [{"role": r.role, "content": r.message} for r in rows]


def fallback_queue(
    session,
    order_data: Any,
    reason: str = "",
    trace_id: Optional[str] = None
) -> None:
    """
    Сохраняет заказ (или payload) в таблице failed_orders (FailedOrder).
    Для повторной переобработки или анализа.
    """
    f = FailedOrder(
        order_data=str(order_data),
        reason=reason,
        trace_id=trace_id,
        created_at=datetime.utcnow()
    )
    session.add(f)
    session.commit()

    slog.error(
        "order_fallback",
        trace_id=trace_id,
        reason=reason,
        order_data=order_data
    )


def reprocess_fallback_orders(
    session,
    orchestrator_sender_fn,
    max_retry: int = 3
):
    """
    Пример функции, которая берёт записи из failed_orders и пытается 
    переотправить их в Orchestrator. 
    orchestrator_sender_fn — функция, которая принимает order_data, trace_id и делает requests.post.
    """
    failed_list = session.query(FailedOrder).all()

    for fobj in failed_list:
        slog.info(
            "reprocess_fallback_start",
            fallback_id=fobj.id,
            trace_id=fobj.trace_id
        )
        success = False
        for attempt in range(1, max_retry + 1):
            slog.info(
                "fallback_send_attempt",
                attempt=attempt,
                fallback_id=fobj.id,
                trace_id=fobj.trace_id
            )
            try:
                resp = orchestrator_sender_fn(
                    order_data=fobj.order_data,
                    trace_id=fobj.trace_id
                )
                if resp:
                    # Если успех, удаляем запись из FailedOrder
                    session.delete(fobj)
                    session.commit()
                    slog.info(
                        "fallback_reprocessed_success",
                        fallback_id=fobj.id,
                        trace_id=fobj.trace_id
                    )
                    success = True
                    break
            except Exception as ex:
                slog.error(
                    "fallback_reprocess_error",
                    error=str(ex),
                    fallback_id=fobj.id,
                    trace_id=fobj.trace_id
                )
            time.sleep(RETRY_DELAY)

        if not success:
            slog.error(
                "fallback_reprocessed_failed",
                fallback_id=fobj.id,
                trace_id=fobj.trace_id
            )

###############################################################################
# GPT-ЛОГИКА (принимаем gpt_service)
###############################################################################


def use_gpt_s(
    session,
    order_id: int,
    user_message: str,
    gpt_service,
    faq_data: Optional[str] = None
) -> str:
    """
    Общение с GPT: добавляет user-сообщение, 
    собирает контекст, вызывает GPT, добавляет assistant-ответ.

    :param user_message: Текст, который клиент (или "user") отправляет.
    :param faq_data: Доп. данные FAQ, чтобы GPT могло опираться на известную инфу.
    """
    # Записываем сообщение
    add_dialog_message(session, order_id, "user", user_message)

    base_system_prompt = (
        "You are GPT-S, a specialized AI assistant. "
        "Communicate with the client in a helpful, polite manner, "
        "avoid errors and keep clarity. If they ask about the company, "
        "use the known data or provided FAQ.\n"
    )
    if faq_data:
        base_system_prompt += f"\n[FAQ reference]\n{faq_data}\n"

    existing_dialog = get_dialog_messages(session, order_id)

    # Формируем список сообщений для ChatCompletion
    messages = [{"role": "system", "content": base_system_prompt}]
    for msg in existing_dialog:
        # Приводим role=user -> "user", role=assistant -> "assistant" и т. д.
        # Если у нас в БД role может быть "user"/"assistant"/"aggregator",
        # то для GPT логики: "system"/"user"/"assistant".
        # Можно сделать простое сопоставление:
        if msg["role"] not in ["system", "assistant", "user"]:
            gpt_role = "user" if msg["role"] == "aggregator" else msg["role"]
        else:
            gpt_role = msg["role"]
        messages.append({"role": gpt_role, "content": msg["content"]})

    # Вызываем GPT-сервис (предполагается, что gpt_service.chat_completion(messages) -> str)
    try:
        assistant_msg = gpt_service.chat_completion(messages)
    except Exception as ex:
        slog.error("gpt_error", error=str(ex))
        assistant_msg = (
            "Извините, возникла ошибка при обращении к AI. Попробуйте позднее."
        )

    # Записываем ответ
    add_dialog_message(session, order_id, "assistant", assistant_msg)
    return assistant_msg


###############################################################################
# ВСПОМОГАТЕЛЬНАЯ ФУНКЦИЯ ОТПРАВКИ НА ORCHESTRATOR
###############################################################################
def send_to_orchestrator(
    session,
    order_data: Dict[str, Any],
    trace_id: Optional[str] = None
) -> Optional[Dict[str, Any]]:
    """
    Отправляет заказ (JSON) в Orchestrator по эндпоинту ORCHESTRATOR_URL.
    При неудаче -> fallback_queue.

    :param session: объект сессии БД
    :param order_data: словарь с параметрами заказа (topic, language, ...)
    :param trace_id: идентификатор трассировки для логов
    :return: Распарсенный JSON-ответ от Orchestrator (dict) или None при ошибке.
    """
    try:
        resp = requests.post(
            f"{ORCHESTRATOR_URL}/order",
            json=order_data,
            timeout=5
        )
        if resp.ok:
            return resp.json()
        else:
            reason = f"HTTP {resp.status_code}: {resp.text}"
            fallback_queue(session, order_data, reason, trace_id)
            return None

    except requests.exceptions.RequestException as e:
        fallback_queue(session, order_data, str(e), trace_id)
        return None


###############################################################################
# ГЛАВНАЯ ФУНКЦИЯ: process_new_orders
###############################################################################
def process_new_orders(
    session,
    upwork_client,
    gpt_service,
    trace_id: Optional[str] = None
):
    """
    1) Получает список jobs с UpWork (или другой биржи).
    2) Валидирует и создаёт Order в БД.
    3) Пытается (с ретраями) отправить в Orchestrator.
    4) При успехе -> устанавливаем статус IN_PROGRESS, при неудаче -> FAILED.
    5) Пример обращения к GPT для уточнения информации или генерации сообщения.
    """
    jobs = upwork_client.fetch_jobs()  # Возвращает список словарей с полями
    slog.info("fetched_jobs", count=len(jobs), trace_id=trace_id)

    for job in jobs:
        title = job.get("title")
        if not title or not isinstance(title, str):
            slog.warning("skip_invalid_title", title=title, trace_id=trace_id)
            continue

        amount = job.get("amount")
        try:
            price = float(amount)
        except (TypeError, ValueError):
            slog.warning("skip_invalid_amount", title=title,
                         amount=amount, trace_id=trace_id)
            continue

        external_client_id = job.get("client", {}).get("client_id")
        client_name = job.get("client", {}).get("name", "UpWorkClient")
        is_urgent = job.get("is_urgent", False)
        language = job.get("language", "en")
        job_id = job.get("job_id")

        # Пример доп. проверки: Если language не поддерживаем, пропустим
        # if language not in SUPPORTED_LANGS:
        #     slog.info("skip_unsupported_lang", title=title, language=language)
        #     continue

        order_id = record_order(
            session=session,
            topic=title,
            language=language,
            client_name=client_name,
            price=price,
            is_urgent=is_urgent,
            external_client_id=external_client_id,
            job_id=job_id,
            initial_status=OrderStatus.NEW
        )

        # Формируем payload для Orchestrator
        order_payload = {
            "topic": title,
            "language": language,
            "client_name": client_name,
            "price": price,
            "is_urgent": is_urgent,
            "external_client_id": external_client_id,
            "job_id": job_id
        }

        # Цикл ретраев при отправке
        for attempt in range(1, MAX_RETRIES + 1):
            slog.info("orchestrator_send_attempt", attempt=attempt,
                      order_id=order_id, trace_id=trace_id)
            response_data = send_to_orchestrator(
                session, order_payload, trace_id)
            if response_data:
                # Успех
                update_order_status(session, order_id, OrderStatus.IN_PROGRESS)
                # Пример запроса GPT
                user_q = "Здравствуйте! Как быстро вы сможете начать работу над моим проектом?"
                gpt_answer = use_gpt_s(
                    session, order_id, user_q, gpt_service=gpt_service)
                slog.info("gpt_answer_on_creation", gpt_answer=gpt_answer)
                break
            else:
                slog.warning(
                    "orchestrator_send_failed",
                    order_id=order_id,
                    attempt=attempt,
                    trace_id=trace_id
                )
                time.sleep(RETRY_DELAY)
        else:
            # Если вышли из for по else — все попытки исчерпаны
            slog.error("max_retries_exceeded",
                       order_id=order_id, trace_id=trace_id)
            update_order_status(
                session, order_id, OrderStatus.FAILED, reason="Orchestrator unreachable")


###############################################################################
# ЗАПУСК ФОНОВОГО ЦИКЛА (MVP). В ПРОДАКШЕНЕ -> CELERY/CRON/systemd
###############################################################################
def run_orders_loop(upwork_client, gpt_service):
    """
    Простейший цикл для примера, который раз в MAIN_INTERVAL
    вызывает process_new_orders. 
    В продакшене предпочтительнее Celery beat, systemd timer или Cronjob.
    """
    slog.info("orders_loop_start", interval=MAIN_INTERVAL)

    while True:
        with SessionLocal() as session:
            # Генерируем trace_id (если не приходит снаружи)
            local_trace_id = str(uuid.uuid4())[:8]
            process_new_orders(
                session,
                upwork_client,
                gpt_service,
                trace_id=local_trace_id
            )

            # Дополнительно пробуем переобработать fallback-очередь
            # (Можно делать реже или в другом цикле)
            reprocess_fallback_orders(
                session,
                orchestrator_sender_fn=lambda order_data, trace_id: send_to_orchestrator(
                    session, order_data, trace_id),
                max_retry=2
            )

        time.sleep(MAIN_INTERVAL)


###############################################################################
# ВЕБХУК/ОБРАБОТКА СООБЩЕНИЙ ОТ КЛИЕНТА (handle_client_message)
###############################################################################
def handle_client_message(
    order_id: int,
    user_message: str,
    external_client_id: Optional[str] = None,
    upwork_client=None,
    gpt_service=None,
    trace_id: Optional[str] = None
) -> str:
    """
    Пример приёма сообщения от клиента (через webhook или REST-эндпоинт).
    1) Проверяем, что заказ существует.
    2) Проверяем соответствие external_client_id (если нужно).
    3) Записываем user-сообщение, вызываем GPT, возвращаем ответ.

    :param order_id: ID заказа
    :param user_message: Текст сообщения
    :param external_client_id: ID клиента (для проверки)
    :param upwork_client: На случай, если нужно дополнительно запросить UpWork
    :param gpt_service: Сервис для генерации ответов
    :param trace_id: Идентификатор трассировки для логов
    :return: Строка ответа от GPT или ошибка.
    """
    with SessionLocal() as session:
        order_obj = session.get(Order, order_id)
        if not order_obj:
            slog.warning("handle_client_no_order",
                         order_id=order_id, trace_id=trace_id)
            return "Заказ не найден."

        # Проверяем external_client_id (если передан)
        if external_client_id and order_obj.external_client_id != external_client_id:
            slog.warning(
                "handle_client_wrong_external_id",
                order_id=order_id,
                trace_id=trace_id,
                got_external_id=external_client_id,
                stored_external_id=order_obj.external_client_id
            )
            return "Ошибка: вы не являетесь владельцем этого заказа."

        # Записываем сообщение от клиента
        add_dialog_message(session, order_id, "user", user_message)

        if not gpt_service:
            slog.warning("no_gpt_service", order_id=order_id,
                         trace_id=trace_id)
            return "GPT-сервис недоступен, попробуйте позднее."

        # GPT-ответ
        reply = use_gpt_s(session, order_id, user_message,
                          gpt_service=gpt_service)
        slog.info("handle_client_gpt_reply", order_id=order_id,
                  trace_id=trace_id, reply=reply)
        return reply
