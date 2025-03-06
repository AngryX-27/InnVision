"""
routers/health.py — здесь объявляем эндпоинты для проверки здоровья сервиса.
Содержит /health и /ping, а также пример проверки базы данных.
"""

import time
import logging
from typing import Dict, Any, Optional

from fastapi import APIRouter, Response, status

# Предположим, вы хотите проверить соединение с БД (необязательно).
# Если не нужно, закомментируйте/уберите соответствующие части кода.
try:
    from aggregator_service.aggregator_db.session import aggregator_db_session
    DB_AVAILABLE = True
except ImportError:
    # Если aggregator_db/session.py не доступен или не нужен
    DB_AVAILABLE = False

logger = logging.getLogger(__name__)

router = APIRouter()
START_TIME = time.time()  # Запоминаем время старта приложения


def get_uptime() -> float:
    """
    Возвращает, сколько секунд работает сервис с момента старта.
    """
    return time.time() - START_TIME


@router.get("/ping", summary="Ping endpoint", tags=["health"])
def ping() -> Dict[str, str]:
    """
    Простейший health-check:
    Возвращает 'pong', чтобы быстро проверить, что сервис откликается.
    """
    return {"message": "pong"}


@router.get("/health", summary="Расширенный health-check", tags=["health"])
def health_check(response: Response, check_db: bool = False) -> Dict[str, Any]:
    """
    Главный эндпоинт для проверки работоспособности сервиса.
    - Возвращает статус (ok), uptime (sec).
    - Если query-param check_db=true, дополнительно пытается сделать запрос SELECT 1 к БД.

    Пример вызова: GET /health?check_db=true
    """
    data = {
        "status": "ok",
        "uptime_seconds": round(get_uptime(), 2)
    }

    # Если нужно проверить базу
    if check_db and DB_AVAILABLE:
        try:
            # Простейший тест: выполняем SELECT 1
            with aggregator_db_session() as db:
                db.execute("SELECT 1")
            data["db_status"] = "ok"
        except Exception as e:
            logger.warning(f"[health] DB check failed: {e}")
            data["db_status"] = f"error: {e}"
            # Можно выставить HTTP 503 (service unavailable), если важно
            response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    elif check_db and not DB_AVAILABLE:
        data["db_status"] = "not_configured"

    return data
