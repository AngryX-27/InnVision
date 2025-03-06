"""
orchestrator_dispatcher.py

Небольшой модуль для отправки готового ТЗ (Task Document) в Оркестратор.
Здесь Aggregator:
  1) берёт JSONB из tz_documents (через tz_storage_db), 
  2) POST'ит его на эндпоинт Оркестратора (e.g. /orders),
  3) в случае успеха может обновить TЗ, пометив "dispatched".

Использует:
 - requests
 - tenacity (для повторных попыток при 429/5xx)
 - aggregator_service.db (SessionLocal)
 - aggregator_service.logic.tz_storage_db (get_tz, update_tz)
 - logging для логов

Предположим, Orchestrator слушает на http://orchestrator:5000
и ожидает POST /orders (json=tz_data).
"""

import requests
import logging
import time
from typing import Dict, Any

from tenacity import (
    retry,
    wait_exponential,
    stop_after_attempt,
    retry_if_exception_type,
)

from aggregator_service.db import SessionLocal
from aggregator_service.logic.tz_storage_db import get_tz, update_tz

logger = logging.getLogger(__name__)

# Или из config (settings.ORCHESTRATOR_URL)
ORCHESTRATOR_URL = "http://orchestrator:5000"


class OrchestratorSendError(Exception):
    """Исключение, если не удалось отправить ТЗ в Оркестратор."""


@retry(
    reraise=True,
    wait=wait_exponential(multiplier=1, min=1, max=10),
    stop=stop_after_attempt(3),
    retry=retry_if_exception_type(requests.RequestException),
)
def _post_with_retries(url: str, json_data: dict, timeout: int = 10) -> requests.Response:
    """
    Посылает POST с повторами (3 попытки) при сетевых / 429 / 5xx ошибках
    (через tenacity).
    :param url: полный URL (e.g. http://orchestrator:5000/orders)
    :param json_data: dict to send in JSON body
    :param timeout: int, HTTP timeout
    :return: Response (успешный)
    :raises requests.RequestException: если после повторов не получилось
    """
    resp = requests.post(url, json=json_data, timeout=timeout)
    if resp.status_code >= 400:
        logger.error("Orchestrator responded HTTP %s: %s",
                     resp.status_code, resp.text)
        if resp.status_code in (429, 500, 502, 503, 504):
            raise requests.RequestException(
                f"Retryable {resp.status_code}: {resp.text}")
        # Если 4xx (например 400, 401), тоже бросаем Exception,
        # но уже не будет ретраев, так как
        # retry_if_exception_type(RequestException) => we re-raise
        resp.raise_for_status()
    return resp


def send_tz_to_orchestrator(order_id: str) -> Dict[str, Any]:
    """
    1) Загружаем TЗ (JSONB) из tz_documents по order_id
    2) POST'им его на Оркестратор (http://orchestrator:5000/orders) (c повторами при 429/5xx)
    3) Если успех -> можно обновить TЗ (set 'dispatched'=True)
    4) Возвращаем r.json() или {"error":...}

    :param order_id: идентификатор заказа (fiverr_XXX / upwork_YYY / etc.)
    :return: dict (ответ от оркестратора) либо {"error":"..."} при неудаче
    """
    logger.info("Preparing to send TЗ to Orchestrator, order_id=%s", order_id)

    # 1) Загружаем TЗ
    with SessionLocal() as session:
        tz_data = get_tz(session, order_id)

    if not tz_data:
        msg = f"No TЗ found for order_id={order_id}, cannot send to Orchestrator."
        logger.warning(msg)
        return {"error": msg}

    orchestrator_endpoint = f"{ORCHESTRATOR_URL.rstrip('/')}/orders"
    logger.info("Sending TЗ to Orchestrator: %s (order_id=%s)",
                orchestrator_endpoint, order_id)

    try:
        # 2) POST c повторами
        resp = _post_with_retries(orchestrator_endpoint, tz_data)
        # 3) При успехе
        result_json = resp.json()  # предполагаем, что Orchestrator возвращает JSON

        # (Опционально) Сохраним в TЗ, что оно "dispatched"
        with SessionLocal() as session:
            try:
                update_tz(session, order_id, {
                    "orchestrator_dispatch": {
                        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                        "response": result_json
                    },
                    "status": "dispatched"
                })
            except Exception as e:
                logger.warning("Could not update TЗ with orchestrator_dispatch for order_id=%s: %s",
                               order_id, e)
        logger.info("Orchestrator accepted TЗ for order_id=%s", order_id)
        return result_json
    except requests.RequestException as e:
        msg = f"Failed to send TЗ to Orchestrator after retries: {e}"
        logger.error(msg)
        return {"error": msg}
