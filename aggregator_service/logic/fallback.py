"""
aggregator_service/logic/fallback.py

Расширенный модуль для переотправки ("retry") заказов, которые
сохраняются в таблице failed_orders при сбое отправки в Orchestrator.

Основные улучшения/особенности:
1) Подсчёт попыток (attempts) и ограничение (MAX_ATTEMPTS).
2) Экспоненциальная задержка (exponential backoff) между повторными отправками.
3) Различение 4xx/5xx ошибок при работе с Orchestrator:
   - 4xx -> скорее всего, бессмысленно повторять, переводим в "exhausted" (или удаляем).
   - 5xx -> имеет смысл повторять.
4) Подробное логгирование с использованием structlog.
5) Гибкая конфигурация интервала и времени ожидания (из config.py).
6) Хранение причины неудачи в поле "reason" для анализа.
7) Возможность уведомлять о "перманентно" неотправленных заказах (если attempts > MAX_ATTEMPTS).

Запуск:
- Обычно запускается в отдельном воркере (docker-контейнере), 
  либо под управлением Celery (можно перенести логику в Celery-задачу).
- В случае отдельного контейнера запускается main() и крутится цикл с интервалом.

Примечание: Если у вас уже есть Celery, можно сделать celery task для retry_failed_orders.
"""

import time
import json
import traceback
import math
import datetime

import structlog  # Если используете structlog
from sqlalchemy import and_

from aggregator_service.db import SessionLocal
from aggregator_service.aggregator_db.models import FailedOrder
from aggregator_service.config.config import (
    logger,  # Стандартный logger, если нужен
    # Интервал основного цикла fallback в секундах (например, 60)
    SLEEP_BETWEEN_CYCLES,
    MAX_ATTEMPTS,  # Максимум попыток, напр. 10
    EXP_BACKOFF_BASE,  # Основа экспоненциальной задержки, напр. 2.0
    EXP_BACKOFF_MULTIPLIER,  # Доп. множитель, например 1.0 (коэффициент)
    ALLOW_BACKOFF,  # Флаг, включать ли экспоненциальный бэкофф
)
from aggregator_service.logic.orders import send_to_orchestrator

# Пример инициализации structlog (может быть вынесено в другое место)
slog = structlog.get_logger(__name__)


def retry_failed_orders(session):
    """
    Повторная отправка заказов, застрявших в таблице failed_orders.

    Алгоритм:
      1) Находим все записи, у которых attempts < MAX_ATTEMPTS.
         (при желании можно фильтровать ещё и по next_attempt_at <= now)
      2) Для каждой записи:
         - Парсим order_data из JSON
         - Вычисляем, нужно ли уже пытаться заново (с учётом next_attempt_at и текущего времени)
         - Если да, вызываем process_single_failed_record(...)
    """

    # Пример: фильтруем только те, у которых attempts < MAX_ATTEMPTS
    # и у которых next_attempt_at <= now, если храните подобное поле
    now = datetime.datetime.utcnow()
    query = session.query(FailedOrder).filter(
        FailedOrder.attempts < MAX_ATTEMPTS)

    # Если в модели есть поле next_attempt_at, можно так:
    # query = query.filter(
    #     and_(
    #         FailedOrder.attempts < MAX_ATTEMPTS,
    #         FailedOrder.next_attempt_at <= now
    #     )
    # )

    records = query.all()
    if not records:
        slog.debug("retry_no_records", msg="Нет записей для ретрая.")
        return

    for rec in records:
        success = process_single_failed_record(session, rec)
        if success:
            # Успех: удаляем запись
            session.delete(rec)
            session.commit()
            slog.info(
                "retry_record_removed",
                failed_order_id=rec.id,
                attempts=rec.attempts,
                trace_id=rec.trace_id
            )
        else:
            # Неудача: attempts + 1, возможно обновляем next_attempt_at
            rec.attempts += 1
            rec.updated_at = now

            # Если включён экспоненциальный бэкофф
            if ALLOW_BACKOFF:
                # next_attempt = now + (EXP_BACKOFF_MULTIPLIER * (EXP_BACKOFF_BASE ^ attempts))
                # Но т.к. ^ — это XOR, используем math.pow или оператор **
                delay_seconds = (EXP_BACKOFF_MULTIPLIER *
                                 math.pow(EXP_BACKOFF_BASE, rec.attempts))
                rec.next_attempt_at = now + \
                    datetime.timedelta(seconds=delay_seconds)
            else:
                # Иначе можно задать фиксированный отступ (например, 60 сек):
                rec.next_attempt_at = now + datetime.timedelta(seconds=60)

            session.commit()

            if rec.attempts >= MAX_ATTEMPTS:
                # Превысили лимит попыток
                slog.error(
                    "retry_exceeded_max_attempts",
                    failed_order_id=rec.id,
                    attempts=rec.attempts,
                    trace_id=rec.trace_id
                )
                # Можно удалить запись или пометить специальным флагом
                # Например, rec.status = 'exhausted' (если есть такое поле)
                # session.delete(rec)
                # session.commit()
                # Или: rec.reason = "Exhausted attempts"
                #     rec.status = 'exhausted'
                #     session.commit()


def process_single_failed_record(session, rec: FailedOrder) -> bool:
    """
    Обрабатывает одиночную запись из failed_orders:
      - Парсит order_data;
      - Вызывает send_to_orchestrator(...);
      - Анализирует ответ:
         - Если успех -> возвращаем True
         - Если 4xx (irrecoverable) -> записываем reason, возвращаем False (и, возможно, сразу помечаем exhausted)
         - Если 5xx или таймаут -> возвращаем False (будем повторять)
    """
    try:
        order_data = json.loads(rec.order_data)
    except (ValueError, TypeError) as e:
        slog.warning(
            "retry_failed_json_parse",
            failed_order_id=rec.id,
            error=str(e)
        )
        # Вряд ли имеет смысл повторять заказ, если order_data не парсится
        rec.reason = f"JSON parse error: {e}"
        return False

    slog.info(
        "retry_attempt",
        failed_order_id=rec.id,
        attempts=rec.attempts,
        trace_id=rec.trace_id
    )

    # Пробуем повторно вызвать send_to_orchestrator
    try:
        # Предположим, send_to_orchestrator вернёт None при ошибке
        # или dict c ключами (например: {'status_code': 200, 'data': {...}}).
        # Если у вас другой формат, адаптируйте ниже.

        response_data = send_to_orchestrator(
            session=session,
            order_data=order_data,
            trace_id=rec.trace_id
        )

        # Если None -> точно ошибка
        if response_data is None:
            slog.warning(
                "retry_send_failed_no_response",
                failed_order_id=rec.id,
                trace_id=rec.trace_id
            )
            rec.reason = "No response from Orchestrator"
            return False

        # Проверяем код ответа, если мы его передаём:
        # Например, response_data.get('status_code')
        status_code = response_data.get('status_code')
        if status_code is None:
            # Может быть, логика у вас другая.
            # Тут считаем что если нет кода, но resp != None, значит успех
            slog.info(
                "retry_send_success_no_statuscode",
                failed_order_id=rec.id,
                trace_id=rec.trace_id
            )
            return True

        # Если есть status_code, различаем 2xx/4xx/5xx:
        if 200 <= status_code < 300:
            # Успех
            slog.info(
                "retry_send_success",
                failed_order_id=rec.id,
                trace_id=rec.trace_id,
                status_code=status_code
            )
            return True
        elif 400 <= status_code < 500:
            # Скорее всего, бессмысленно повторять
            slog.error(
                "retry_send_4xx",
                failed_order_id=rec.id,
                trace_id=rec.trace_id,
                status_code=status_code
            )
            rec.reason = f"Received 4xx from Orchestrator ({status_code})."
            # Возвращаем False, но можно сразу пометить 'exhausted'
            return False
        elif 500 <= status_code < 600:
            # Ошибка на стороне Orchestrator, можно повторять
            slog.warning(
                "retry_send_5xx",
                failed_order_id=rec.id,
                trace_id=rec.trace_id,
                status_code=status_code
            )
            rec.reason = f"Received 5xx from Orchestrator ({status_code})."
            return False
        else:
            # Другой код: 300-399 (redirect?), 600+ (нестандартный?)
            slog.warning(
                "retry_send_unexpected_code",
                failed_order_id=rec.id,
                trace_id=rec.trace_id,
                status_code=status_code
            )
            rec.reason = f"Unexpected status code: {status_code}."
            return False

    except Exception as exc:
        # Ловим любые другие эксепшены (ConnectionError, Timeout, etc.)
        err_info = traceback.format_exc()
        slog.error(
            "retry_send_exception",
            failed_order_id=rec.id,
            trace_id=rec.trace_id,
            error=str(exc)
        )
        rec.reason = f"Exception: {str(exc)}\nTrace: {err_info}"
        return False


def main():
    """
    Точка входа при запуске fallback в отдельном воркере (контейнере):
      - Бесконечный цикл:
          1) Создаём session
          2) retry_failed_orders(session)
          3) sleep SLEEP_BETWEEN_CYCLES

      - Если возникает непредвиденная ошибка, логируем и продолжаем.
      - При желании, можно сделать Celery-задачу вместо while True.
    """

    slog.info("[fallback] Fallback worker start",
              interval=SLEEP_BETWEEN_CYCLES)
    while True:
        try:
            with SessionLocal() as session:
                retry_failed_orders(session)
        except Exception:
            err_info = traceback.format_exc()
            slog.error("[fallback] runtime_error", error=err_info)

        time.sleep(SLEEP_BETWEEN_CYCLES)


if __name__ == "__main__":
    main()
