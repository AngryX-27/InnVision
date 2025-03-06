"""
aggregator_service/logic/proposals.py

Расширенный модуль с бизнес-логикой, связанной с формированием и отправкой заявок (proposals)
на биржу (UpWork или другую платформу).

Основные задачи:
1. Генерация текста предложения (pitch) через GPT (generate_proposal_text).
2. Отправка proposal на внешнюю биржу (send_proposal_to_upwork).
3. Обновление статуса заявки в БД (update_order_proposal_status).
4. Обработка ответа/коллбэка (handle_proposal_response).
5. Хранение всей переписки (add_dialog_message) в таблице client_dialogs.

Особенности:
- Использует structlog для более гибкого и детального логгирования.
- Предусмотрены ретраи при неуспешной отправке пропозала.
- Поддерживаются несколько статусов заявки (Draft, Sent, Accepted, Declined, Interview, Hired, Failed).

Пример использования:
    create_and_send_proposal(order_id=123)

Автор: 
(Ваше имя/команда)
"""

import time
import structlog  # для примера расширенного логгирования
from enum import Enum
from typing import Optional, Dict, Any

from aggregator_service.db import SessionLocal
from aggregator_service.aggregator_db.models import Order, ClientDialog
from aggregator_service.services.upwork_client import UpWorkClient
from aggregator_service.services.gpt_service import GPTService
from aggregator_service.config.config import (
    UPWORK_API_URL,
    UPWORK_ACCESS_TOKEN,
    PITCH_TEMPLATE,
    MAX_RETRIES,
    RETRY_DELAY,
    # если объявлен в config.py (альтернативно используйте structlog.get_logger())
    logger
)

###############################################################################
# Пример инициализации structlog (можно вынести в config/инициализатор)
###############################################################################
slog = structlog.get_logger(__name__)

###############################################################################
# ПЕРЕЧИСЛЕНИЕ СТАТУСОВ PROPOSAL
###############################################################################


class ProposalStatus(str, Enum):
    DRAFT = "draft"
    SENT = "sent"
    ACCEPTED = "accepted"
    DECLINED = "declined"
    INTERVIEW = "interview"
    HIRED = "hired"
    FAILED = "failed"


# Допустимые переходы между статусами заявки
ALLOWED_PROPOSAL_TRANSITIONS = {
    ProposalStatus.DRAFT: [ProposalStatus.SENT, ProposalStatus.FAILED],
    ProposalStatus.SENT: [
        ProposalStatus.ACCEPTED,
        ProposalStatus.DECLINED,
        ProposalStatus.INTERVIEW,
        ProposalStatus.HIRED,
        ProposalStatus.FAILED
    ],
    ProposalStatus.ACCEPTED: [ProposalStatus.FAILED],
    ProposalStatus.DECLINED: [],
    ProposalStatus.INTERVIEW: [
        ProposalStatus.ACCEPTED,
        ProposalStatus.DECLINED,
        ProposalStatus.FAILED,
        ProposalStatus.HIRED
    ],
    ProposalStatus.HIRED: [],
    ProposalStatus.FAILED: []
}


###############################################################################
# УТИЛИТАРНЫЕ ФУНКЦИИ РАБОТЫ С БД (CRUD для proposal_status, диалоги)
###############################################################################
def update_order_proposal_status(session, order_id: int, new_status: ProposalStatus) -> None:
    """
    Обновляет поле proposal_status в Order, соблюдая таблицу допустимых переходов.
    Если переход недопустим, выведет предупреждение и не изменит статус.

    :param session: SQLAlchemy session
    :param order_id: ID заказа
    :param new_status: Новый статус заявки (ProposalStatus)
    :return: None
    """
    order_obj = session.get(Order, order_id)
    if not order_obj:
        slog.warning("proposal_status_update_no_order", order_id=order_id)
        return

    old_status = order_obj.proposal_status or ProposalStatus.DRAFT.value
    try:
        old_status_enum = ProposalStatus(old_status)
    except ValueError:
        slog.warning("proposal_status_invalid_old",
                     order_id=order_id, old_status=old_status)
        return

    if new_status not in ALLOWED_PROPOSAL_TRANSITIONS.get(old_status_enum, []):
        slog.warning(
            "invalid_proposal_transition",
            order_id=order_id,
            from_status=old_status_enum.value,
            to_status=new_status.value
        )
        return

    order_obj.proposal_status = new_status.value
    session.commit()

    slog.info(
        "proposal_status_updated",
        order_id=order_id,
        old_status=old_status_enum.value,
        new_status=new_status.value
    )


def add_dialog_message(session, order_id: int, role: str, message: str, msg_type: str = "text") -> None:
    """
    Записывает новое сообщение в таблицу client_dialogs, привязанное к order_id.
    :param session: SQLAlchemy session
    :param order_id: идентификатор заказа
    :param role: 'user', 'assistant', 'system', 'aggregator' и т.д.
    :param message: текст сообщения
    :param msg_type: текст, файл, ссылка — на ваше усмотрение
    """
    dialog_entry = ClientDialog(
        order_id=order_id,
        role=role,
        message=message,
        message_type=msg_type
    )
    session.add(dialog_entry)
    session.commit()
    slog.debug(
        "dialog_message_added",
        order_id=order_id,
        role=role,
        msg_preview=message[:50]
    )


###############################################################################
# ИНИЦИАЛИЗАЦИЯ СЕРВИСОВ (UPWORK, GPT)
# Обычно делается в главном модуле, но для наглядности — здесь.
###############################################################################
upwork_client = UpWorkClient(
    base_url=UPWORK_API_URL,
    token=UPWORK_ACCESS_TOKEN,
    logger=logger  # или slog если хотите
)

gpt_service = GPTService(
    model="gpt-4",
    temperature=0.7,
    max_tokens=500,
    logger=logger,
    retry_count=3,
    retry_delay=2
)


###############################################################################
# ГЕНЕРАЦИЯ ТЕКСТА ПРОПОЗАЛА (PITCH) ЧЕРЕЗ GPT
###############################################################################
def generate_proposal_text(
    topic: str,
    client_name: str,
    price: float,
    language: str = "en",
    additional_info: str = ""
) -> str:
    """
    Формируем красивый pitch (cover letter) с помощью GPT, используя шаблон PITCH_TEMPLATE.
    :param topic: Тема/название проекта
    :param client_name: Имя клиента (или компания)
    :param price: Предполагаемая цена или ставка
    :param language: Основной язык проекта
    :param additional_info: Доп. сведения, которые нужно учесть в промпте
    :return: Сгенерированный GPT текст пропозала
    """
    system_prompt = (
        "You are a professional freelance writer with expertise in creating persuasive proposals. "
        "Use the given template or user-provided prompt to form a clear, concise pitch. "
        "Be polite, professional, and highlight relevant experience.\n"
    )

    # Собираем user-промпт (через PITCH_TEMPLATE)
    user_prompt = (
        f"{PITCH_TEMPLATE}\n\n"
        f"Topic: {topic}\n"
        f"Client: {client_name}\n"
        f"Proposed Price: {price}\n"
        f"Language: {language}\n"
        f"Additional info: {additional_info}\n\n"
        "Please write a short cover letter addressing the client directly."
    )

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt}
    ]

    try:
        response_text = gpt_service.chat_completion(messages)
        slog.info("generated_proposal_text",
                  topic=topic, client_name=client_name)
        return response_text
    except Exception as ex:
        slog.error("gpt_error_generating_proposal", error=str(ex))
        return (
            "We encountered an error while generating your proposal. Please try again or adjust parameters."
        )


###############################################################################
# ОТПРАВКА PROPOSAL НА UPWORK
###############################################################################
def send_proposal_to_upwork(
    order_id: int,
    proposal_text: str,
    price: float,
    language: str = "en",
    additional_params: Optional[Dict[str, Any]] = None
) -> Optional[str]:
    """
    Отправляет созданное письмо (cover_letter) на биржу (UpWork).
    :param order_id: ID заказа (используется в логах)
    :param proposal_text: Текст пропозала
    :param price: Ставка/бюджет
    :param language: язык
    :param additional_params: словарь с доп. полями (job_id, attachments, и т.д.)
    :return: Идентификатор proposal (str) при успехе, либо None
    """
    proposal_data = {
        "cover_letter": proposal_text,
        "charge_rate": price,
        "language": language
    }
    if additional_params:
        proposal_data.update(additional_params)

    try:
        response = upwork_client.create_proposal(proposal_data)
        if response.get("status") == "success":
            proposal_id = response.get("proposal_id")
            slog.info("proposal_sent_success",
                      order_id=order_id, proposal_id=proposal_id)
            return proposal_id
        else:
            slog.warning("proposal_send_failed",
                         order_id=order_id, response=response)
            return None
    except Exception as e:
        slog.error("proposal_send_exception", order_id=order_id, error=str(e))
        return None


###############################################################################
# СОСТАВЛЕНИЕ И ОТПРАВКА PROPOSAL (ОСНОВНАЯ ФУНКЦИЯ)
###############################################################################
def create_and_send_proposal(order_id: int) -> None:
    """
    Основная функция для создания и отправки пропозала:
      1) Получает заказ из БД (Order).
      2) Генерирует текст (GPT).
      3) Делает несколько попыток (ретраи) отправить пропозал на UpWork.
      4) При успехе -> устанавливает статус proposal_status='sent'
      5) При неудаче -> proposal_status='failed'
      6) Сохраняет текст пропозала в client_dialogs.

    :param order_id: ID заказа
    :return: None
    """
    with SessionLocal() as session:
        order_obj = session.get(Order, order_id)
        if not order_obj:
            slog.warning("proposal_creation_no_order", order_id=order_id)
            return

        topic = order_obj.topic or "Untitled Project"
        client_name = order_obj.client_name or "Client"
        price = float(order_obj.price or 0.0)
        language = order_obj.language or "en"
        job_id = order_obj.job_id  # предположим, у нас есть поле job_id
        additional_info = "We have strong experience in this domain."

        # Генерируем текст пропозала
        proposal_text = generate_proposal_text(
            topic=topic,
            client_name=client_name,
            price=price,
            language=language,
            additional_info=additional_info
        )

        # Записываем пропозал в dialog (для истории)
        add_dialog_message(session, order_id, "assistant",
                           f"Draft proposal:\n{proposal_text}")

        # Обновляем статус на DRAFT, если он ещё не был установлен
        if not order_obj.proposal_status:
            update_order_proposal_status(
                session, order_id, ProposalStatus.DRAFT)

        proposal_id = None

        for attempt in range(1, MAX_RETRIES + 1):
            slog.info(
                "sending_proposal_attempt",
                order_id=order_id,
                attempt=attempt,
                max_tries=MAX_RETRIES
            )
            proposal_id = send_proposal_to_upwork(
                order_id=order_id,
                proposal_text=proposal_text,
                price=price,
                language=language,
                additional_params={"job_id": job_id} if job_id else {}
            )

            if proposal_id:
                # Успех
                update_order_proposal_status(
                    session, order_id, ProposalStatus.SENT)
                add_dialog_message(session, order_id, "assistant",
                                   f"Proposal SENT (ID={proposal_id})")
                slog.info("proposal_sent", order_id=order_id,
                          proposal_id=proposal_id)
                break
            else:
                slog.warning("proposal_not_sent",
                             order_id=order_id, attempt=attempt)
                time.sleep(RETRY_DELAY)
        else:
            # Если цикл for завершился без break
            slog.error("proposal_failed_all_attempts", order_id=order_id)
            update_order_proposal_status(
                session, order_id, ProposalStatus.FAILED)


###############################################################################
# ОБРАБОТКА ОТВЕТА ОТ КЛИЕНТА (WEBHOOK/CALLBACK ИЛИ ПОЛУЧЕНИЕ СЧЕТА)
###############################################################################
def handle_proposal_response(order_id: int, response_data: Dict[str, Any]) -> str:
    """
    Обработка ответа с биржи о статусе пропозала (accepted, declined, interview, hired, etc.).
    Предположим, что платформа (UpWork) отправляет JSON, где есть 'status' и 'message'.
    В зависимости от пришедшего статуса - обновляем proposal_status.

    :param order_id: ID заказа
    :param response_data: dict с ключами: {'status': 'accepted'/'declined'/'interview'..., 'message': '...'}
    :return: Строка с итоговым статусом (или сообщение об ошибке).
    """
    with SessionLocal() as session:
        order_obj = session.get(Order, order_id)
        if not order_obj:
            slog.warning("handle_proposal_response_no_order",
                         order_id=order_id)
            return "Order not found."

        status = response_data.get("status")
        message = response_data.get("message", "")

        if not status:
            slog.warning("handle_proposal_response_no_status",
                         order_id=order_id, data=response_data)
            return "No status provided in response."

        # Пробуем преобразовать в ProposalStatus (можем маппить, если UpWorkStatuses отличаются)
        # Например, если UpWork вернёт "AWAITING_INTERVIEW" -> вы мапите на ProposalStatus.INTERVIEW
        # Ниже — упрощённый пример:
        status_lower = status.lower()
        if status_lower not in ProposalStatus._value2member_map_:
            # допустим, если платформа присылает что-то другое,
            # можно дополнительно обработать
            slog.warning("unknown_proposal_status",
                         order_id=order_id, status=status_lower)
            return f"Unknown status '{status}'."

        new_status = ProposalStatus(status_lower)

        # Записываем сообщение в диалоги
        add_dialog_message(session, order_id, "system",
                           f"Proposal status changed: {new_status.value}\n{message}")

        # Меняем статус заказа, если переход допустим
        update_order_proposal_status(session, order_id, new_status)
        slog.info("proposal_status_changed_by_callback",
                  order_id=order_id, new_status=new_status.value)

        return f"Proposal status updated to '{new_status.value}'."
