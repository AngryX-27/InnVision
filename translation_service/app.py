"""
app.py — основной входной файл микросервиса Translation Service.
Здесь инициализируется FastAPI, подключаются роуты, обрабатываются ошибки.
"""

import uvicorn
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse

# Настройки (порт, ключи API, ENV и т.д.)
from translation_service.config import settings

# Логгер (использует get_logger из logger.py)
from translation_service.utils.logger import get_logger

# Инициализация БД (подключение, сессии).
# Предполагается, что миграции делает Alembic, а init_db() лишь тестирует соединение.
# Допустим, что close_db() тоже у нас определён
from aggregator_service.aggregator_db.session import init_db, close_db

# Роуты (эндпоинты)
from translation_service.routers.translation import router as translation_router
from translation_service.routers.health import router as health_router

logger = get_logger(__name__)
# первоначальное создание, далее будет переопределено в create_app()
app: FastAPI = FastAPI()


def create_app() -> FastAPI:
    """
    Функция, создающая и настраивающая экземпляр FastAPI.
    """
    app = FastAPI(
        title="Translation Service",
        version="1.0.0",
        description="Микросервис для перевода текстов (GPT/DeepL/Google)."
    )

    # 1) Инициализация базы данных (проверяем соединение, конфиги и т.д.)
    #
    # По комментариям предполагалось, что init_db() не делает create_all(), а только тестит соединение.
    # Однако в aggregator_service/aggregator_db/session.py init_db может реально вызвать create_all().
    # Если это нежелательно, нужно править саму реализацию init_db в session.py.
    #
    init_db()  # НЕ делает create_all() (по задумке), только тест подключения (если это уже исправлено в session.py)

    # 2) Подключаем роуты
    app.include_router(translation_router, prefix="/api", tags=["translation"])
    app.include_router(health_router, prefix="/api", tags=["health"])

    # 3) Регистрируем глобальные обработчики исключений
    register_exception_handlers(app)

    # 4) События on_startup и on_shutdown
    @app.on_event("startup")
    async def on_startup() -> None:
        logger.info("Translation Service is starting up...")
        # Логируем ключевую информацию о среде и настройках
        logger.info(f"ENV mode: {settings.ENV}")
        logger.info(f"Listening on port: {settings.PORT}")
        logger.info(f"Database URL: {settings.DB_URL}")
        logger.info(
            f"Chunking is {'enabled' if settings.ALLOW_CHUNKING else 'disabled'}.")
        if settings.DEBUG:
            logger.debug("Debug mode is active!")

    @app.on_event("shutdown")
    async def on_shutdown() -> None:
        logger.info("Translation Service is shutting down...")
        # Закрываем соединение с БД (пример)
        # Предполагаем, что в db.database есть функция close_db()
        try:
            close_db()
            logger.info("DB connection closed successfully.")
        except Exception as e:
            logger.warning(f"Error closing DB connection: {e}")

        # Завершаем фоновые задачи (если вы используете Celery, asyncio.TaskGroup, etc.)
        # Пример: await shutdown_background_tasks() — демонстрационно
        # logger.info("All background tasks completed.")

    return app


def register_exception_handlers(app: FastAPI) -> None:
    """
    Регистрируем глобальные обработчики исключений для FastAPI-приложения.
    """
    @app.exception_handler(HTTPException)
    async def http_exception_handler(request: Request, exc: HTTPException):
        logger.warning(
            f"HTTPException: {exc.detail} (status={exc.status_code})")
        return JSONResponse(
            status_code=exc.status_code,
            content={"error": exc.detail},
        )

    @app.exception_handler(Exception)
    async def general_exception_handler(request: Request, exc: Exception):
        logger.error(f"Unhandled exception: {exc}", exc_info=True)
        return JSONResponse(
            status_code=500,
            content={"error": "Internal Server Error"},
        )


# Создаём приложение (принято именовать app)
app = create_app()

# Точка входа при локальном запуске (python app.py)
if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=settings.PORT)
