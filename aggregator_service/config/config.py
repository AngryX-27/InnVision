import os
import logging
from dotenv import load_dotenv

# 1) Подхватываем .env
load_dotenv(override=True)


class Config:
    """
    Класс, хранящий все основные настройки проекта,
    читаемые из .env (или окружения), с дефолтами.

    Пример использования:
        config = Config()
        print(config.AGGREGATOR_DB_URL)
    """

    # ----------------------------
    # Агрегатор (Aggregator)
    # ----------------------------
    AGGREGATOR_PORT: int = int(os.getenv("AGGREGATOR_PORT", "5002"))

    # Интервал, кол-во попыток и т.д. (если используете)
    MAIN_INTERVAL: int = int(os.getenv("MAIN_INTERVAL", "60"))
    AGGREGATOR_MAX_RETRIES: int = int(os.getenv("AGGREGATOR_MAX_RETRIES", "7"))
    AGGREGATOR_RETRY_DELAY: int = int(os.getenv("AGGREGATOR_RETRY_DELAY", "5"))

    # Логирование
    AGGREGATOR_LOG_LEVEL: str = os.getenv(
        "AGGREGATOR_LOG_LEVEL", "INFO").upper()
    AGGREGATOR_LOG_FILE: str = os.getenv("AGGREGATOR_LOG_FILE", "")

    # OpenAI (GPT) ключ, если нужно
    OPENAI_API_KEY: str = os.getenv("OPENAI_API_KEY", "")

    # ----------------------------
    # Агрегатор Fallback (если используете)
    # ----------------------------
    AGGREGATOR_FALLBACK_PORT: int = int(
        os.getenv("AGGREGATOR_FALLBACK_PORT", "5004"))

    # ----------------------------
    # UpWork
    # ----------------------------
    UPWORK_API_URL: str = os.getenv(
        "UPWORK_API_URL", "https://www.upwork.com/api/v3")
    UPWORK_ACCESS_TOKEN: str = os.getenv(
        "UPWORK_ACCESS_TOKEN", "YOUR_UPWORK_TOKEN_PLACEHOLDER")

    # ----------------------------
    # Fiverr (если используете)
    # ----------------------------
    FIVERR_ENABLED: bool = os.getenv(
        "FIVERR_ENABLED", "true").lower() == "true"
    FIVERR_USERNAME: str = os.getenv("FIVERR_USERNAME", "")
    FIVERR_PASSWORD: str = os.getenv("FIVERR_PASSWORD", "")
    FIVERR_COOKIE: str = os.getenv("FIVERR_COOKIE", "")

    # ----------------------------
    # Orchestrator
    # ----------------------------
    ORCHESTRATOR_PORT: int = int(os.getenv("ORCHESTRATOR_PORT", "5000"))
    ORCHESTRATOR_URL: str = os.getenv(
        "ORCHESTRATOR_URL", "http://orchestrator:5000")

    # ----------------------------
    # Role General
    # ----------------------------
    ROLE_GENERAL_PORT: int = int(os.getenv("ROLE_GENERAL_PORT", "5001"))

    # ----------------------------
    # QA Service
    # ----------------------------
    QA_SERVICE_PORT: int = int(os.getenv("QA_SERVICE_PORT", "5003"))

    # ----------------------------
    # Translation Service
    # ----------------------------
    TRANSLATION_SERVICE_PORT: int = int(
        os.getenv("TRANSLATION_SERVICE_PORT", "5005"))
    TRANSLATION_SERVICE_ENV: str = os.getenv(
        "TRANSLATION_SERVICE_ENV", "development")

    # ----------------------------
    # DB - aggregator_db
    # ----------------------------
    AGGREGATOR_DB_USER: str = os.getenv(
        "AGGREGATOR_DB_USER", "aggregator_user")
    AGGREGATOR_DB_PASS: str = os.getenv(
        "AGGREGATOR_DB_PASS", "aggregator_pass")
    AGGREGATOR_DB_NAME: str = os.getenv("AGGREGATOR_DB_NAME", "aggregator_db")
    AGGREGATOR_DB_HOST: str = os.getenv("AGGREGATOR_DB_HOST", "aggregator_db")
    AGGREGATOR_DB_PORT: int = int(os.getenv("AGGREGATOR_DB_PORT", "5432"))

    AGGREGATOR_DB_URL: str = os.getenv(
        "AGGREGATOR_DB_URL",
        f"postgresql://{AGGREGATOR_DB_USER}:{AGGREGATOR_DB_PASS}@{AGGREGATOR_DB_HOST}:{AGGREGATOR_DB_PORT}/{AGGREGATOR_DB_NAME}"
    )

    # ----------------------------
    # DB - translation_db (если используете)
    # ----------------------------
    TRANSLATION_DB_USER: str = os.getenv(
        "TRANSLATION_DB_USER", "translation_user")
    TRANSLATION_DB_PASS: str = os.getenv(
        "TRANSLATION_DB_PASS", "translation_pass")
    TRANSLATION_DB_NAME: str = os.getenv(
        "TRANSLATION_DB_NAME", "translation_db")
    TRANSLATION_DB_HOST: str = os.getenv(
        "TRANSLATION_DB_HOST", "translation_db")
    TRANSLATION_DB_PORT: int = int(os.getenv("TRANSLATION_DB_PORT", "5432"))

    TRANSLATION_DB_URL: str = os.getenv(
        "TRANSLATION_DB_URL",
        f"postgresql://{TRANSLATION_DB_USER}:{TRANSLATION_DB_PASS}@{TRANSLATION_DB_HOST}:{TRANSLATION_DB_PORT}/{TRANSLATION_DB_NAME}"
    )

    # ----------------------------
    # Дополнительные настройки
    # ----------------------------
    PITCH_TEMPLATE: str = os.getenv("PITCH_TEMPLATE", "Default pitch template")
    MAX_RETRIES: int = int(os.getenv("MAX_RETRIES", "3"))
    RETRY_DELAY: int = int(os.getenv("RETRY_DELAY", "2"))

    # ----------------------------
    # Настройки fallback-логики (SLEEP_BETWEEN_CYCLES, MAX_ATTEMPTS и пр.)
    # ----------------------------
    SLEEP_BETWEEN_CYCLES: int = int(os.getenv("SLEEP_BETWEEN_CYCLES", "60"))
    MAX_ATTEMPTS: int = int(os.getenv("MAX_ATTEMPTS", "10"))
    EXP_BACKOFF_BASE: float = float(os.getenv("EXP_BACKOFF_BASE", "2.0"))
    EXP_BACKOFF_MULTIPLIER: float = float(
        os.getenv("EXP_BACKOFF_MULTIPLIER", "1.0"))
    ALLOW_BACKOFF: bool = os.getenv("ALLOW_BACKOFF", "true").lower() == "true"

    DB_URL: str = os.getenv(
        "DB_URL", "postgresql://username:password@localhost:5432/mydb")


###############################################################################
# Настройка глобального логгера (если нужно)
###############################################################################
def setup_logging() -> logging.Logger:
    """
    Настраивает глобальный логгер на основе config.py значений.
    Можно расширять (JSONFormatter, handlers). Здесь - минималистичный вариант.
    """
    cfg = Config()  # создаём инстанс
    logger = logging.getLogger("aggregator_service")
    logger.setLevel(cfg.AGGREGATOR_LOG_LEVEL)

    fmt = "[%(asctime)s] %(levelname)s %(name)s: %(message)s"
    datefmt = "%Y-%m-%d %H:%M:%S"
    formatter = logging.Formatter(fmt=fmt, datefmt=datefmt)

    # Вывод в консоль
    console_handler = logging.StreamHandler()
    console_handler.setLevel(cfg.AGGREGATOR_LOG_LEVEL)
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)

    # Вывод в файл (если указано)
    if cfg.AGGREGATOR_LOG_FILE:
        try:
            file_handler = logging.FileHandler(
                cfg.AGGREGATOR_LOG_FILE, mode="a")
            file_handler.setLevel(cfg.AGGREGATOR_LOG_LEVEL)
            file_handler.setFormatter(formatter)
            logger.addHandler(file_handler)
        except Exception as e:
            logger.warning(
                f"Не удалось открыть файл логов '{cfg.AGGREGATOR_LOG_FILE}': {e}"
            )

    return logger


# ----------------------------
# Создаём единый экземпляр конфигурации и логгера
# ----------------------------
config = Config()
logger = setup_logging()

# Пример warning, если видим placeholder
if "PLACEHOLDER" in config.UPWORK_ACCESS_TOKEN:
    logger.warning("UPWORK_ACCESS_TOKEN всё ещё placeholder! Проверьте .env")

if not config.FIVERR_ENABLED:
    logger.info("FIVERR_ENABLED=false. Fiverr-интеграция отключена.")


# ----------------------------
# Экспорт переменных на уровне модуля
# (чтобы можно было импортировать напрямую: from aggregator_service.config.config import ...)
# ----------------------------
UPWORK_API_URL = config.UPWORK_API_URL
UPWORK_ACCESS_TOKEN = config.UPWORK_ACCESS_TOKEN
ORCHESTRATOR_URL = config.ORCHESTRATOR_URL
MAIN_INTERVAL = config.MAIN_INTERVAL

PITCH_TEMPLATE = config.PITCH_TEMPLATE
MAX_RETRIES = config.MAX_RETRIES
RETRY_DELAY = config.RETRY_DELAY

SLEEP_BETWEEN_CYCLES = config.SLEEP_BETWEEN_CYCLES
MAX_ATTEMPTS = config.MAX_ATTEMPTS
EXP_BACKOFF_BASE = config.EXP_BACKOFF_BASE
EXP_BACKOFF_MULTIPLIER = config.EXP_BACKOFF_MULTIPLIER
ALLOW_BACKOFF = config.ALLOW_BACKOFF
