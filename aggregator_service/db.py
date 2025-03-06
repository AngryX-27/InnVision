"""
db.py

"Боевая" версия со встроенной поддержкой Alembic миграций.
 - Создаёт движок (pool, pre_ping, password masking).
 - Объявляет Base и SessionLocal.
 - Импортирует ваши модели (чтобы Alembic видел таблицы).
 - Если AUTO_MIGRATE=true, автоматически вызывает 'alembic upgrade head'.
"""

import os
from urllib.parse import urlparse, urlunparse

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base

# Alembic
from alembic.config import Config as AlembicConfig
from aggregator_service.alembic import command

# Импортируем общий config/логгер
from aggregator_service.config.config import config, logger

###############################################################################
# МОДЕЛИ
###############################################################################
# !!! ВАЖНО: Если у вас есть пакет 'aggregator_service.models',
# импортуем его здесь, чтобы все модели были видны при autogenerate.
# (Если у вас модели в другом месте, подкорректируйте импорт.)
try:
    from aggregator_service.model import Order, ClientDialog, FailedOrder
    # Если моделей больше, импортируйте их тоже
except ImportError:
    # Если нет такого модуля, можно пропустить или залогировать
    logger.warning(
        "Не удалось импортировать aggregator_service.models (Order, ClientDialog...)")

###############################################################################
# ФУНКЦИЯ МАСКИРОВКИ ПАРОЛЯ
###############################################################################


def sanitize_db_url(db_url: str) -> str:
    """
    Маскирует пароль в DSN, чтобы не утекал в логи.
    Пример:
       postgresql://user:pass@host:5432/db -> postgresql://user:***@host:5432/db
    Если пароля нет, возвращает исходную строку.
    """
    parsed = urlparse(db_url)
    if parsed.password:
        masked_netloc = f"{parsed.username}:***@{parsed.hostname}"
        if parsed.port:
            masked_netloc += f":{parsed.port}"
        return urlunparse((
            parsed.scheme,
            masked_netloc,
            parsed.path or "",
            parsed.params,
            parsed.query,
            parsed.fragment
        ))
    return db_url


###############################################################################
# ПАРАМЕТРЫ ПУЛА
###############################################################################
POOL_SIZE = int(os.getenv("DB_POOL_SIZE", "5"))
MAX_OVERFLOW = int(os.getenv("DB_MAX_OVERFLOW", "10"))
POOL_TIMEOUT = int(os.getenv("DB_POOL_TIMEOUT", "30"))
POOL_RECYCLE = int(os.getenv("DB_POOL_RECYCLE", "1800"))
POOL_PRE_PING = os.getenv("DB_POOL_PRE_PING", "true").lower() == "true"

###############################################################################
# СОЗДАЁМ ENGINE
###############################################################################
raw_db_url = config.DB_URL
sanitized_url = sanitize_db_url(raw_db_url)

logger.info("Initializing database engine with DSN: %s", sanitized_url)

engine = create_engine(
    raw_db_url,
    pool_size=POOL_SIZE,
    max_overflow=MAX_OVERFLOW,
    pool_timeout=POOL_TIMEOUT,
    pool_recycle=POOL_RECYCLE,
    pool_pre_ping=POOL_PRE_PING,
    echo=False,  # echo=True для отладки (выводит все SQL-запросы)
    future=True
)

SessionLocal = sessionmaker(
    autocommit=False,
    autoflush=False,
    bind=engine,
    future=True
)

# Объявляем базовый класс ORM
Base = declarative_base()

# !!! Важно: если ваши модели объявлены не здесь, а в aggregator_service.models,
#            нужно, чтобы при импорте выше они "подцепились" к этому Base.
#            Часто делают: models.Base = db.Base, либо всё в одном месте.


###############################################################################
# ALEMBIC MIGRATIONS
###############################################################################
def run_migrations_on_startup():
    """
    Запускает Alembic-команду 'upgrade head',
    чтобы привести БД к последней версии миграций.
    """
    # Предположим, у вас есть alembic.ini в корне проекта или в aggregator_service/.
    # Подставьте корректный путь:
    alembic_ini_path = os.path.join(
        # aggregator_service/ (если db.py тут лежит)
        os.path.dirname(__file__),
        "..",                       # поднимаемся на уровень выше,
        "alembic.ini"              # (или где лежит ваш alembic.ini)
    )

    alembic_cfg = AlembicConfig(alembic_ini_path)

    # Если в alembic.ini не прописан sqlalchemy.url, можно установить:
    # alembic_cfg.set_main_option("sqlalchemy.url", str(engine.url))

    logger.info("Running Alembic migrations from config: %s", alembic_ini_path)
    command.upgrade(alembic_cfg, "head")


# Если AUTO_MIGRATE=true, при старте пытаемся применить все миграции
if os.getenv("AUTO_MIGRATE", "false").lower() == "true":
    logger.info("AUTO_MIGRATE=true - запускаем Alembic миграции (upgrade head).")
    try:
        run_migrations_on_startup()
    except Exception as e:
        logger.error("Ошибка при миграции: %s", e)
        raise

###############################################################################
# ПРИМЕР РАБОТЫ С СЕССИЕЙ
###############################################################################
# with SessionLocal() as session:
#     ... ORM ...
#
# Или через Depends (FastAPI).
###############################################################################
