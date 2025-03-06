"""
logger.py — продвинутая настройка логирования в Translation Service.

1) Читает конфиг из config.py (или fallback к os.getenv).
2) Поддерживает JSON-формат (через python-json-logger) и обычный текстовый формат.
3) Умеет ротацию по времени (TimedRotatingFileHandler) или размеру (RotatingFileHandler).
4) Пример использования нескольких file-обработчиков (error_file_handler + info_file_handler)
   и консольного обработчика.
5) Предотвращает дублирование хендлеров, если логгер уже инициализирован.
"""

import logging
import os
from logging import Logger
from logging.handlers import TimedRotatingFileHandler, RotatingFileHandler

# Если вы хотите JSON-лог, установите python-json-logger:
# pip install python-json-logger
try:
    from pythonjsonlogger import jsonlogger
    JSON_LOGGER_AVAILABLE = True
except ImportError:
    JSON_LOGGER_AVAILABLE = False

# ===== Попробуем импортировать ваши pydantic-настройки (config.py) =====
try:
    # предполагается, что это ваш pydantic Settings
    from translation_service.config import settings
    # Читаем параметры
    LOG_LEVEL = getattr(settings, "LOG_LEVEL", "INFO").upper()
    LOG_FORMAT = getattr(settings, "LOG_FORMAT",
                         "%(asctime)s [%(levelname)s] %(name)s: %(message)s")
    LOG_DIR = getattr(settings, "LOG_DIR", "./logs")
    LOG_FILENAME = getattr(settings, "LOG_FILENAME", "translation_service.log")
    LOG_ROTATION = getattr(settings, "LOG_ROTATION",
                           "time").lower()  # "time" / "size"
    LOG_ROTATE_WHEN = getattr(settings, "LOG_ROTATE_WHEN", "midnight")
    LOG_ROTATE_INTERVAL = getattr(settings, "LOG_ROTATE_INTERVAL", 1)
    LOG_ROTATE_BACKUP_COUNT = getattr(settings, "LOG_ROTATE_BACKUP_COUNT", 7)
    LOG_ROTATE_MAX_BYTES = getattr(
        settings, "LOG_ROTATE_MAX_BYTES", 10485760)  # 10MB
    LOG_ROTATE_BACKUP_COUNT_SIZE = getattr(
        settings, "LOG_ROTATE_BACKUP_COUNT_SIZE", 5)
    # если в настройках есть такой флаг
    USE_JSON_LOGS = getattr(settings, "USE_JSON_LOGS", False)
except ImportError:
    # Fallback: читаем напрямую из окружения
    LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()
    LOG_FORMAT = os.getenv(
        "LOG_FORMAT", "%(asctime)s [%(levelname)s] %(name)s: %(message)s")
    LOG_DIR = os.getenv("LOG_DIR", "./logs")
    LOG_FILENAME = os.getenv("LOG_FILENAME", "translation_service.log")
    LOG_ROTATION = os.getenv("LOG_ROTATION", "time").lower()
    LOG_ROTATE_WHEN = os.getenv("LOG_ROTATE_WHEN", "midnight")
    LOG_ROTATE_INTERVAL = int(os.getenv("LOG_ROTATE_INTERVAL", "1"))
    LOG_ROTATE_BACKUP_COUNT = int(os.getenv("LOG_ROTATE_BACKUP_COUNT", "7"))
    LOG_ROTATE_MAX_BYTES = int(os.getenv("LOG_ROTATE_MAX_BYTES", "10485760"))
    LOG_ROTATE_BACKUP_COUNT_SIZE = int(
        os.getenv("LOG_ROTATE_BACKUP_COUNT_SIZE", "5"))
    USE_JSON_LOGS = os.getenv(
        "USE_JSON_LOGS", "false").lower() in ("true", "1", "yes")


# Проверяем валидность LOG_ROTATION
if LOG_ROTATION not in ("time", "size"):
    logging.warning(
        f"Неверный LOG_ROTATION='{LOG_ROTATION}', используем 'time'.")
    LOG_ROTATION = "time"


def _create_file_handler(
    level: int,
    log_file: str,
    rotation_mode: str
) -> logging.Handler:
    """
    Создаёт FileHandler c заданным уровнем и ротацией.
    rotation_mode: "time" или "size"
    """
    if not os.path.exists(LOG_DIR):
        os.makedirs(LOG_DIR)

    if rotation_mode == "time":
        handler = TimedRotatingFileHandler(
            filename=log_file,
            when=LOG_ROTATE_WHEN,
            interval=LOG_ROTATE_INTERVAL,
            backupCount=LOG_ROTATE_BACKUP_COUNT,
            encoding="utf-8"
        )
    else:
        handler = RotatingFileHandler(
            filename=log_file,
            maxBytes=LOG_ROTATE_MAX_BYTES,
            backupCount=LOG_ROTATE_BACKUP_COUNT_SIZE,
            encoding="utf-8"
        )

    handler.setLevel(level)
    if USE_JSON_LOGS and JSON_LOGGER_AVAILABLE:
        formatter = jsonlogger.JsonFormatter(LOG_FORMAT)
    else:
        formatter = logging.Formatter(LOG_FORMAT)

    handler.setFormatter(formatter)
    return handler


def _create_stream_handler(level: int) -> logging.Handler:
    """
    Создаёт обработчик для вывода логов в консоль (stdout).
    """
    stream_handler = logging.StreamHandler()
    stream_handler.setLevel(level)
    if USE_JSON_LOGS and JSON_LOGGER_AVAILABLE:
        formatter = jsonlogger.JsonFormatter(LOG_FORMAT)
    else:
        formatter = logging.Formatter(LOG_FORMAT)
    stream_handler.setFormatter(formatter)
    return stream_handler


def get_logger(name: str = __name__) -> Logger:
    """
    Возвращает логгер с несколькими хендлерами:
      1) file_handler_info: записывает INFO и выше
      2) file_handler_error: записывает WARNING и выше в другой файл
      3) stream_handler: вывод в консоль (DEBUG и выше)
    """
    logger = logging.getLogger(name)
    if logger.handlers:
        # уже инициализирован
        return logger

    # Уровень логгера = DEBUG (выше фильтра по хендлерам)
    logger.setLevel(logging.DEBUG)

    # 1) file_handler для INFO+ (вся информация, ротация)
    info_log_path = os.path.join(LOG_DIR, LOG_FILENAME)
    file_handler_info = _create_file_handler(
        logging.INFO, info_log_path, LOG_ROTATION)

    # 2) отдельный file_handler для WARNING+ (можно назвать error.log), если хотите
    error_log_path = os.path.join(LOG_DIR, "error_" + LOG_FILENAME)
    file_handler_error = _create_file_handler(
        logging.WARNING, error_log_path, LOG_ROTATION)

    # 3) консольный handler (StreamHandler) — DEBUG+
    console_handler = _create_stream_handler(logging.DEBUG)

    logger.addHandler(file_handler_info)
    logger.addHandler(file_handler_error)
    logger.addHandler(console_handler)

    # Можно отключить всплытие логов к родителям:
    logger.propagate = False

    logger.debug(
        f"[Logger init] name='{name}', JSON={USE_JSON_LOGS}, rotation='{LOG_ROTATION}', level='{LOG_LEVEL}'")
    return logger


if __name__ == "__main__":
    # Пример использования локально
    test_logger = get_logger("test_logger")
    test_logger.debug("Сообщение DEBUG")
    test_logger.info("Сообщение INFO")
    test_logger.warning("Сообщение WARNING")
    test_logger.error("Сообщение ERROR")
    test_logger.critical("Сообщение CRITICAL")
