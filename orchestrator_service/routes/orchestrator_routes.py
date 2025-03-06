# orchestrator_routes.py

import logging
import uuid
from typing import Optional, Any
from flask import Blueprint, request, jsonify, g
from werkzeug.exceptions import HTTPException
from pydantic import ValidationError

# Предположим, что в orchestrator.py у вас есть:
# Orchestrator, OrderIn, OrderResult, OrderStatus
# а также кастомные исключения (RoleClientError, QAClientRejectedContent и т.д.),
# если вы хотите их здесь различать.
from orchestrator_service.logic.orchestrator import (
    orchestrator_instance,  # Экземпляр Orchestrator, создан в app.py
    OrderIn,
    OrderResult,
    OrderStatus,
    # Допустим, есть кастомные исключения:
    # RoleClientError, QAClientRejectedContent, TranslationClientError, ...
)

logger = logging.getLogger(__name__)
orchestrator_bp = Blueprint("orchestrator_bp", __name__)

########################################################################
# 1. Перед каждым запросом: генерируем / берём request_id
########################################################################


@orchestrator_bp.before_app_request
def assign_request_id():
    """
    Если есть X-Request-ID, берём его, иначе генерируем свой.
    Сохраняем в flask.g.request_id для логирования.
    """
    req_id = request.headers.get("X-Request-ID")
    if not req_id:
        req_id = str(uuid.uuid4())
    g.request_id = req_id
    logger.info(
        f"[{req_id}] Start request: {request.path} (method={request.method})")

########################################################################
# 2. Основной эндпоинт: POST /orchestrator/order
#    Принимает JSON, валидирует, вызывает Orchestrator
########################################################################


@orchestrator_bp.route("/order", methods=["POST"])
def handle_order():
    request_id = getattr(g, "request_id", "no-request-id")
    raw_data = request.get_json(silent=True)

    if raw_data is None:
        logger.warning(f"[{request_id}] Invalid or missing JSON body.")
        return error_response(
            status_code=400,
            request_id=request_id,
            error_type="InvalidJSON",
            message="Отсутствует или некорректный формат JSON"
        )

    # Валидируем вход через Pydantic
    try:
        order_in = OrderIn(**raw_data)
    except ValidationError as ve:
        logger.warning(f"[{request_id}] ValidationError: {ve.errors()}")
        return error_response(
            status_code=400,
            request_id=request_id,
            error_type="ValidationError",
            message="Некорректные поля во входном JSON",
            details=ve.errors()
        )

    logger.info(
        f"[{request_id}] handle_order (order_id={order_in.order_id}) - start orchestrator")

    try:
        # Вызываем Orchestrator
        result: OrderResult = orchestrator_instance.handle_order(
            order_in, request_id=request_id)

        # Возвращаем JSON-ответ
        return success_response(
            request_id=request_id,
            data=result.dict()
        )

    except HTTPException as he:
        logger.exception(f"[{request_id}] HTTPException: {he}")
        return error_response(
            status_code=he.code,
            request_id=request_id,
            error_type="HTTPException",
            message=he.description
        )

    # Пример, если хотите перехватывать кастомные исключения:
    # except QAClientRejectedContent as qc:
    #     logger.exception(f"[{request_id}] QA Rejected: {qc}")
    #     return error_response(
    #         status_code=422,
    #         request_id=request_id,
    #         error_type="QARejectedContent",
    #         message=str(qc)
    #     )

    except Exception as e:
        logger.exception(f"[{request_id}] Unknown error in handle_order: {e}")
        return error_response(
            status_code=500,
            request_id=request_id,
            error_type="UnknownError",
            message=str(e)
        )

########################################################################
# 3. Эндпоинт: GET /orchestrator/status/<order_id>
#    Возвращает текущий статус заказа (или 404)
########################################################################


@orchestrator_bp.route("/status/<int:order_id>", methods=["GET"])
def get_order_status(order_id):
    request_id = getattr(g, "request_id", "no-request-id")
    logger.info(f"[{request_id}] get_order_status - order_id={order_id}")

    try:
        # Предположим, Orchestrator имеет метод get_status(order_id)
        # или вы достаёте из базы
        status = orchestrator_instance.get_status(order_id)

        if not status:
            logger.warning(f"[{request_id}] Order {order_id} not found.")
            return error_response(
                status_code=404,
                request_id=request_id,
                error_type="NotFound",
                message=f"Заказ {order_id} не найден"
            )

        return success_response(
            request_id=request_id,
            data={
                "order_id": order_id,
                "order_status": status
            }
        )

    except Exception as e:
        logger.exception(f"[{request_id}] Error in get_order_status: {e}")
        return error_response(
            status_code=500,
            request_id=request_id,
            error_type="UnknownError",
            message=str(e)
        )

########################################################################
# 4. Healthcheck: GET /orchestrator/health
########################################################################


@orchestrator_bp.route("/health", methods=["GET"])
def health():
    request_id = getattr(g, "request_id", "no-request-id")
    logger.info(f"[{request_id}] Healthcheck called.")
    # При желании проверить базу / сервисы:
    # aggregator_db_session.execute("SELECT 1")  или orchestrator_instance.ping()

    return success_response(
        request_id=request_id,
        data={
            "service": "orchestrator_service",
            "status": "ok"
        }
    )

########################################################################
# 5. (Опционально) Тестовый эндпоинт /test
########################################################################


@orchestrator_bp.route("/test", methods=["GET"])
def test_endpoint():
    request_id = getattr(g, "request_id", "no-request-id")
    logger.info(f"[{request_id}] Test endpoint called.")
    return success_response(
        request_id=request_id,
        data={
            "hello": "world",
            "info": "Это тестовый эндпоинт"
        }
    )

########################################################################
# 6. Глобальные обработчики внутри Blueprint (необязательно)
########################################################################


@orchestrator_bp.errorhandler(HTTPException)
def handle_http_exc(e):
    request_id = getattr(g, "request_id", "no-request-id")
    logger.warning(f"[{request_id}] HTTPException blueprint: {e.description}")
    return error_response(
        status_code=e.code,
        request_id=request_id,
        error_type="HTTPException",
        message=e.description
    )


@orchestrator_bp.errorhandler(Exception)
def handle_exc(e):
    request_id = getattr(g, "request_id", "no-request-id")
    logger.exception(f"[{request_id}] UnhandledException blueprint: {e}")
    return error_response(
        status_code=500,
        request_id=request_id,
        error_type="UnhandledException",
        message=str(e)
    )


########################################################################
# 7. Вспомогательные функции для форматирования ответов
########################################################################

def success_response(request_id: str, data: dict, code: int = 200):
    """
    Формат успешного ответа:
    {
      "status": "ok",
      "request_id": "...",
      "result": {...}
    }
    """
    return jsonify({
        "status": "ok",
        "request_id": request_id,
        "result": data
    }), code


def error_response(
    status_code: int,
    request_id: str,
    error_type: str,
    message: str,
    details: Optional[Any] = None
):
    """
    Формат ошибки:
    {
      "status": "error",
      "request_id": "...",
      "error_type": "...",
      "message": "...",
      "details": ...
    }
    """
    payload = {
        "status": "error",
        "request_id": request_id,
        "error_type": error_type,
        "message": message
    }
    if details is not None:
        payload["details"] = details

    return jsonify(payload), status_code
