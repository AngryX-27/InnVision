"""
finalize_flow.py

Здесь сосредоточена логика «финализации» заказа (TЗ)
и последующей отправки в Оркестратор.

1) finalize_and_dispatch_order(order_id, final_text):
   - Вызывает finalize_tz(...) из tz_storage_db (устанавливает status='confirmed', final_text=...).
   - Затем send_tz_to_orchestrator(order_id), чтобы POST'ить TЗ в Оркестратор.
   - Возвращает ответ оркестратора.

Доп. замечания:
 - Если TЗ не найдено (get_tz(...) возвращает пусто),
   finalize_tz(...) может бросить исключение ValueError.
 - Orchestrator может вернуть разные ответы, 
   при ошибках можем получить {"error": "..."}.
"""

from aggregator_service.db import SessionLocal
from aggregator_service.logic.tz_storage_db import finalize_tz, get_tz
from aggregator_service.logic.orchestrator_dispatcher import send_tz_to_orchestrator
import logging

logger = logging.getLogger(__name__)


def finalize_and_dispatch_order(order_id: str, final_text: str = "Confirmed"):
    """
    1) Проставляет в TЗ status='confirmed' + final_text,
    2) Вызывает send_tz_to_orchestrator(order_id) для отправки TЗ в Оркестратор,
    3) Возвращает dict (ответ оркестратора) либо {"error":"..."} при ошибках.

    :param order_id: уникальный идентификатор заказа (напр. fiverr_123, upwork_456)
    :param final_text: строка, которая попадёт в doc.data["final_text"] при finalize_tz
    :return: dict, JSON-ответ от Оркестратора (или ошибка).
    """
    logger.info("Finalizing order_id=%s, text=%r", order_id, final_text)

    # 1) Ставим status='confirmed', final_text=...
    with SessionLocal() as session:
        # Получаем doc.data перед финализацией (для логов)
        current_data = get_tz(session, order_id)
        if not current_data:
            logger.warning(
                "No TЗ found for %s - cannot finalize. Possibly an error.", order_id)
        else:
            logger.debug("Current TЗ data before finalize: %s", current_data)

        # finalize_tz (может кинуть ValueError, если нет документа)
        try:
            finalize_tz(session, order_id, final_text)
            logger.info(
                "TЗ for order_id=%s set to status='confirmed', final_text=%r", order_id, final_text)
        except ValueError as e:
            logger.error(
                "Failed to finalize TЗ for order_id=%s: %s", order_id, e)
            return {"error": str(e)}

    # 2) Затем отправляем в Оркестратор
    orchestrator_resp = send_tz_to_orchestrator(order_id)
    logger.info("Orchestrator responded: %s", orchestrator_resp)

    # 3) Возвращаем ответ Оркестратора
    return orchestrator_resp
