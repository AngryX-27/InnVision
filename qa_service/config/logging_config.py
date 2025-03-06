"""
qa_service/config/logging_config.py
-----------------------------------
Расширенная конфигурация логирования для микросервиса QA Service, используя:
- dictConfig
- Параметры из Pydantic (LOG_LEVEL, ENABLE_JSON_LOGS, LOG_FILE и др.)
- JSON-логгер (python-json-logger) при необходимости
- RotatingFileHandler (с ротацией)
- Возможность цветного лога в консоли (colorlog) при желании
- Раздельные уровни логирования для консоли/файла

Использование:
    from config.logging_config import setup_logging
    setup_logging()

После этого можно пользоваться логгерами:
    import logging
    logger = logging.getLogger("qa_service")
    logger.info("Пример лога")
"""

import logging
import logging.config
import os

from typing import Dict, Any

from config.settings import get_settings

try:
    from pythonjsonlogger import jsonlogger
    JSON_LOGGING_AVAILABLE = True
except ImportError:
    JSON_LOGGING_AVAILABLE = False

try:
    import colorlog
    COLORLOG_AVAILABLE = True
except ImportError:
    COLORLOG_AVAILABLE = False


def get_logging_config_dict() -> Dict[str, Any]:
    """
    Формирует dictConfig для logging, учитывая настройки из Pydantic:
    - LOG_LEVEL (общий уровень лога, чаще для root)
    - LOG_CONSOLE_LEVEL (уровень лога для консоли, если нужно)
    - ENABLE_JSON_LOGS (включить ли JSON формат)
    - LOG_FILE (путь к файлу логов; если пусто, файл не используем)
    - LOG_FILE_LEVEL (уровень лога для файла)
    - LOG_MAX_BYTES (размер ротации, по умолчанию 5*1024*1024 = 5 MB)
    - LOG_BACKUP_COUNT (число файлов-бэкапов)
    - DISABLE_EXISTING_LOGGERS (bool; True/False)

    Возвращает словарь, который можно передать в logging.config.dictConfig().
    """

    settings = get_settings()

    # Основные поля
    log_level = settings.LOG_LEVEL.upper()                 # уровень для root
    enable_json_logs = settings.ENABLE_JSON_LOGS
    log_file = settings.LOG_FILE or ""                     # путь к файлу
    # Дополнительные (можно задать в settings.py, а при отсутствии — fallback):
    log_console_level = os.getenv("LOG_CONSOLE_LEVEL", log_level).upper()
    log_file_level = os.getenv("LOG_FILE_LEVEL", log_level).upper()
    log_max_bytes = int(os.getenv("LOG_MAX_BYTES", "5242880"))  # 5 MB
    log_backup_count = int(os.getenv("LOG_BACKUP_COUNT", "3"))
    disable_existing_loggers = os.getenv(
        "DISABLE_EXISTING_LOGGERS", "false").lower() == "true"

    # Базовые форматы
    default_format = "%(asctime)s [%(levelname)s] %(name)s - %(message)s"
    colorlog_format = "%(log_color)s%(asctime)s [%(levelname)s] %(name)s - %(message)s"
    json_format = "%(asctime)s %(levelname)s %(name)s %(message)s"

    # Определим «класс» форматтера для консоли:
    # - Если хотим цветные логи и установлен colorlog -> используем ColoredFormatter
    # - Иначе fallback на обычный logging.Formatter
    if COLORLOG_AVAILABLE:
        console_formatter_class = "colorlog.ColoredFormatter"
    else:
        console_formatter_class = "logging.Formatter"

    # Для JSON (если ENABLE_JSON_LOGS=true и установлен python-json-logger)
    # иначе fallback
    if JSON_LOGGING_AVAILABLE and enable_json_logs:
        json_formatter_class = "pythonjsonlogger.jsonlogger.JsonFormatter"
        chosen_json_format = json_format
    else:
        json_formatter_class = "logging.Formatter"
        chosen_json_format = default_format

    # Форматтер для «обычного» текстового вывода:
    # - если есть colorlog, то цветной, иначе обычный
    # - userdatefmt: "%Y-%m-%d %H:%M:%S"
    formatters = {
        "default": {
            "format": default_format,
            "datefmt": "%Y-%m-%d %H:%M:%S"
        },
        "console_color": {
            "()": console_formatter_class,  # colorlog.ColoredFormatter или logging.Formatter
            "format": colorlog_format if COLORLOG_AVAILABLE else default_format,
            "datefmt": "%Y-%m-%d %H:%M:%S",
            # Доп. настройки для colorlog (можно убрать, если не нужно)
            "log_colors": {
                "DEBUG": "cyan",
                "INFO": "green",
                "WARNING": "yellow",
                "ERROR": "red",
                "CRITICAL": "bold_red",
            }
        },
        "json": {
            "()": json_formatter_class,   # jsonlogger.JsonFormatter или logging.Formatter
            "format": chosen_json_format,
            "datefmt": "%Y-%m-%d %H:%M:%S",
        }
    }

    # --------------------------------------
    # Handlers (минимум console, опционально file)
    # --------------------------------------
    handlers_config = {
        "console": {
            "class": "logging.StreamHandler",
            "level": log_console_level,
            # Если JSON включён, используем "json" форматтер, иначе "console_color"
            "formatter": "json" if (JSON_LOGGING_AVAILABLE and enable_json_logs) else "console_color",
            "stream": "ext://sys.stdout"
        }
    }

    # Если задан log_file, создаём RotatingFileHandler
    if log_file:
        handlers_config["file"] = {
            "class": "logging.handlers.RotatingFileHandler",
            "level": log_file_level,
            # Если JSON включён => "json", иначе "default"
            "formatter": "json" if (JSON_LOGGING_AVAILABLE and enable_json_logs) else "default",
            "filename": log_file,
            "maxBytes": log_max_bytes,
            "backupCount": log_backup_count,
            "encoding": "utf-8"
        }

    logging_config = {
        "version": 1,
        "disable_existing_loggers": disable_existing_loggers,  # по умолчанию False
        "formatters": formatters,
        "handlers": handlers_config,
        # root-логгер (все «неименованные» логи)
        "root": {
            "level": log_level,
            "handlers": list(handlers_config.keys())
        },
        # При желании можно настроить логгеры для отдельных модулей
        # "loggers": {
        #     "some_lib": {
        #         "level": "WARNING",
        #         "handlers": ["console"],
        #         "propagate": False
        #     },
        # }
    }

    return logging_config


def setup_logging() -> None:
    """
    Инициализирует логирование при помощи dictConfig,
    учитывая настройки из Pydantic (settings.py) и дополнительные переменные окружения.
    """
    config_dict = get_logging_config_dict()
    logging.config.dictConfig(config_dict)
    logger = logging.getLogger("qa_service")

    logger.debug("Logging initialized with dictConfig.")
    logger.info("Root logger level set to: %s", config_dict["root"]["level"])

    # Уточним, какие handlers есть
    if "console" in config_dict["handlers"]:
        logger.info("Console logging -> level=%s",
                    config_dict["handlers"]["console"]["level"])
    if "file" in config_dict["handlers"]:
        file_cfg = config_dict["handlers"]["file"]
        logger.info("File logging -> %s (level=%s)",
                    file_cfg["filename"], file_cfg["level"])
    else:
        logger.info("File logging is disabled (LOG_FILE not set or empty).")

    # JSON logging
    from config.settings import get_settings
    s = get_settings()
    if JSON_LOGGING_AVAILABLE and s.ENABLE_JSON_LOGS:
        logger.info("JSON logging is enabled.")
    else:
        logger.info("JSON logging disabled or python-json-logger missing.")

    # Colorlog
    if COLORLOG_AVAILABLE:
        logger.info("Colorlog is available (console logs may be colored).")
    else:
        logger.info("Colorlog not installed or not used.")
