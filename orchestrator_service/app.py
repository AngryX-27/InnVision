# app.py

import logging
import os
import uuid
from flask import Flask, request, g, jsonify
from werkzeug.exceptions import HTTPException
from logging.handlers import RotatingFileHandler
from dotenv import load_dotenv  # Если нужно дополнительно

# Если используете Sentry:
# import sentry_sdk
# from sentry_sdk.integrations.flask import FlaskIntegration

# Предположим, что в config/config.py у вас есть функции load_config(), setup_logging().
# Если нет, вы можете реализовать что-то подобное непосредственно в app.py.
from config.config import load_config, setup_logging

# Импортируем Blueprint, в котором описаны основные эндпоинты Orchestrator
from routes.orchestrator_routes import orchestrator_bp
# (Опционально) Если есть Blueprint для healthcheck
# from routes.health_routes import health_bp

########################################################################
#  Дополнительно: Фильтр для автоматического добавления request_id в логи
########################################################################


class RequestIdFilter(logging.Filter):
    """
    Добавляет в LogRecord атрибут request_id, чтобы использовать его в форматере.
    """

    def filter(self, record):
        record.request_id = getattr(g, "request_id", "no-id")
        return True


def create_app() -> Flask:
    """
    Создаёт и настраивает Flask-приложение (production-сценарий, без разделения окружений).
    """
    # (Опционально) Если нужно подгрузить .env, можно раскомментировать:
    # load_dotenv()

    ############################################################
    # 1. Инициализация приложения Flask
    ############################################################
    app = Flask(__name__)

    ############################################################
    # 2. Загрузка конфигурации из config/config.py
    ############################################################
    config = load_config()          # Предполагаем, что эта функция читает .env/окружение
    app.config.update(config)       # Применяем к Flask

    ############################################################
    # 3. Настройка логирования (консоль + ротация).
    #    Или можно использовать setup_logging() если оно всё делает.
    ############################################################
    setup_logging()                 # Предположим, базовая настройка уже есть

    logger = logging.getLogger()    # Берём root-логгер (или __name__, если нужно)

    # Уровень логирования (INFO по умолчанию)
    log_level_str = os.getenv("LOG_LEVEL", "INFO").upper()
    logger.setLevel(log_level_str)

    # Пример подключения фильтра для request_id
    request_id_filter = RequestIdFilter()
    logger.addFilter(request_id_filter)

    # Если нужно писать в файл с ротацией
    log_file = os.getenv("LOG_FILE", "")
    if log_file:
        max_bytes = int(os.getenv("LOG_ROTATION_MAXBYTES", 1_000_000))
        backup_count = int(os.getenv("LOG_ROTATION_BACKUPCOUNT", 5))
        file_handler = RotatingFileHandler(
            log_file, maxBytes=max_bytes, backupCount=backup_count)
        file_handler.setLevel(log_level_str)
        # Пример обычного форматера. Можно заменить на JSONFormatter, если нужно JSON-лог
        formatter = logging.Formatter(
            '{"time": "%(asctime)s", "level": "%(levelname)s", "name": "%(name)s", '
            '"request_id": "%(request_id)s", "message": "%(message)s"}'
        )
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)

    logger.info("Инициализация логирования и конфигурации завершена.")

    ############################################################
    # 4. (Опционально) Инициализировать Sentry, если есть DSN
    ############################################################
    # sentry_dsn = os.getenv("SENTRY_DSN", "")
    # if sentry_dsn:
    #     sentry_sdk.init(
    #         dsn=sentry_dsn,
    #         integrations=[FlaskIntegration()],
    #         traces_sample_rate=1.0
    #     )
    #     logger.info("Sentry инициализирован с DSN.")

    ############################################################
    # 5. Хуки before_request / after_request для request_id
    ############################################################
    @app.before_request
    def before_request():
        """
        Назначаем всем входящим запросам уникальный request_id (или берём из X-Request-ID),
        чтобы проще искать в логах, а также прокидываться в другие сервисы.
        """
        incoming_req_id = request.headers.get(
            "X-Request-ID", str(uuid.uuid4()))
        g.request_id = incoming_req_id
        logger.info(
            f"Начало обработки запроса: {request.path} (method={request.method})")

    @app.after_request
    def after_request(response):
        """
        Добавляем X-Request-ID в заголовок ответа и логируем итог.
        """
        request_id = getattr(g, "request_id", "no-id")
        response.headers["X-Request-ID"] = request_id
        logger.info(
            f"Окончание обработки: {request.path} - Статус: {response.status_code}")
        return response

    ############################################################
    # 6. Подключаем основной Blueprint (Orchestrator)
    ############################################################
    app.register_blueprint(orchestrator_bp, url_prefix="/orchestrator")

    # (Опционально) если есть health-check:
    # app.register_blueprint(health_bp, url_prefix="/health")

    ############################################################
    # 7. Глобальные обработчики ошибок
    ############################################################
    @app.errorhandler(HTTPException)
    def handle_http_exception(e):
        request_id = g.get("request_id", "no-id")
        logger.warning(f"[{request_id}] HTTPException: {e.description}")
        return jsonify({
            "status": "error",
            "request_id": request_id,
            "error_type": "HTTPException",
            "message": e.description,
            "code": e.code
        }), e.code

    @app.errorhandler(Exception)
    def handle_exception(e):
        request_id = g.get("request_id", "no-id")
        logger.exception(f"[{request_id}] Необработанное исключение: {e}")
        return jsonify({
            "status": "error",
            "request_id": request_id,
            "error_type": "InternalServerError",
            "message": str(e),
            "code": 500
        }), 500

    ############################################################
    # 8. (Опциональный) тестовый эндпоинт, управляемый .env
    ############################################################
    test_endpoint_enabled = os.getenv(
        "TEST_ENDPOINT_ENABLED", "false").lower() == "true"
    if test_endpoint_enabled:
        @app.route("/test", methods=["GET"])
        def test_endpoint():
            """
            Простой эндпоинт, чтобы проверить, живо ли приложение.
            """
            request_id = g.get("request_id", "no-id")
            return jsonify({
                "status": "ok",
                "request_id": request_id,
                "message": "Test endpoint is working!"
            }), 200

    # NEW: ===================================================
    # NEW: Добавляем пример вызова RoleGeneral/QA через функции
    # NEW: и callback-эндпоинт, чтобы показать боевой сценарий
    # NEW: ===================================================

    import requests

    def call_role_general(tz_data: dict) -> str:
        """
        Пример вызова RoleGeneral (POST /generate).
        Возвращает 'draft_text'.
        """
        return "Draft text from RoleGeneral"

    def call_qa_service(text: str) -> dict:
        """
        Пример вызова QAService (POST /check).
        Возвращает структуру: {"status":"ok","issues":[],"suggestions":"..."}
        """
        return {"status": "ok", "issues": [], "suggestions": ""}

    @app.route("/orchestrator/process-order", methods=["POST"])
    def process_order():
        """
        Принимает TЗ (JSON), вызывает RoleGeneral, затем QA, 
        и возвращает финальный результат.
        """
        req_json = request.json or {}
        logger.info(f"Принят TЗ для обработки, req={req_json}")
        # 1) вызов RoleGeneral
        draft_text = call_role_general(req_json)
        # 2) вызов QA
        qa_result = call_qa_service(draft_text)
        # 3) собираем ответ
        final = {
            "draft": draft_text,
            "qa_result": qa_result,
            "status": "done"
        }
        logger.info("Цепочка (RoleGeneral -> QA) завершена.")
        return jsonify(final), 200

    @app.route("/orchestrator/callback", methods=["POST"])
    def aggregator_callback():
        """
        Пример callback, который Aggregator может вызывать 
        (или наоборот, Orchestrator вызывает Aggregator).
        """
        data = request.json or {}
        logger.info(f"Callback получен, data={data}")
        # Можно что-то сохранять в БД Orchestrator
        return jsonify({"message": "Callback OK"}), 200

    # NEW: end of new block

    # NEW: Добавляем HealthCheck эндпоинт (без удаления строк)
    @app.route("/health", methods=["GET"])
    def orchestrator_health():
        """
        Простой эндпоинт для проверки здоровья Orchestrator.
        Возвращает JSON: {"status":"ok","service":"orchestrator"}
        """
        request_id = g.get("request_id", "no-id")
        logger.debug(f"Health-check called. request_id={request_id}")
        return jsonify({
            "status": "ok",
            "service": "orchestrator"
        }), 200

    return app


########################################################################
# 9. Точка входа (при запуске python app.py)
#    Для production лучше Gunicorn:  gunicorn app:application --bind ...
########################################################################
if __name__ == "__main__":
    application = create_app()

    host = application.config.get("ORCHESTRATOR_HOST", "0.0.0.0")
    port = application.config.get("ORCHESTRATOR_PORT", 5000)
    debug_mode = application.config.get("ORCHESTRATOR_DEBUG", False)

    logging.info(
        "Запуск Orchestrator Service через встроенный Flask dev-сервер (prod!).")
    logging.info(
        "В реальном продакшене рекомендуется запуск под Gunicorn/Uvicorn.")
    application.run(host=host, port=port, debug=debug_mode)
