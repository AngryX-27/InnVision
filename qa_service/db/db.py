"""
qa_service/db/db.py
-------------------
Инициализация подключения к базе данных (SQLAlchemy) для QA-сервиса.

Функциональность:
- engine: движок SQLAlchemy (основываясь на DATABASE_URL из Pydantic-настроек).
- SessionLocal: фабрика сессий (sessionmaker).
- get_session(): возвращает новую сессию (не забудьте закрывать её).
- session_scope(): контекстный менеджер (with ...) для автоматического commit/rollback.
- init_db(): опциональная функция для создания таблиц напрямую (Base.metadata.create_all),
  НЕ рекомендуется в продакшене при использовании Alembic.
- health_check_db(): простой тест доступности БД (SELECT 1).

Параметры подключения могут быть дополнительно сконфигурированы 
через настройки (pool_size, max_overflow, pool_timeout и т.д.), если вы хотите
ещё больше контроля над пулом соединений.
"""

import logging
from typing import Optional
from typing import Generator

from contextlib import contextmanager

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session
from sqlalchemy.exc import SQLAlchemyError

from config.settings import get_settings
from db.models import Base  # Нужно, если используем init_db()

logger = logging.getLogger(__name__)

# ------------------------------------------------------------------------------
# Считываем настройки
# ------------------------------------------------------------------------------
settings = get_settings()
DATABASE_URL = settings.DATABASE_URL

# Ниже - пример, если хотите доп. параметры (pool_size и т.д.)
# Если нет нужды, можно удалить или закомментировать.
DB_POOL_SIZE = 5
DB_MAX_OVERFLOW = 10
DB_POOL_TIMEOUT = 30
# Например, можете прочитать из окружения/настроек:
# DB_POOL_SIZE = int(os.getenv("DB_POOL_SIZE", "5"))
# DB_MAX_OVERFLOW = int(os.getenv("DB_MAX_OVERFLOW", "10"))
# DB_POOL_TIMEOUT = int(os.getenv("DB_POOL_TIMEOUT", "30"))

# ------------------------------------------------------------------------------
# Создаём движок
# ------------------------------------------------------------------------------
# Параметр future=True включает поведение SQLAlchemy 2.0 (рекомендуется)
# echo=False - скрыть SQL-запросы (если нужно отладить - echo=True).
engine = create_engine(
    DATABASE_URL,
    echo=False,
    future=True,
    pool_size=DB_POOL_SIZE,
    max_overflow=DB_MAX_OVERFLOW,
    pool_timeout=DB_POOL_TIMEOUT,
    # pool_recycle=1800,  # при необходимости
)

# ------------------------------------------------------------------------------
# Настраиваем фабрику сессий
# ------------------------------------------------------------------------------
SessionLocal = sessionmaker(
    bind=engine,
    autocommit=False,
    autoflush=False,
    future=True
)

# ------------------------------------------------------------------------------
# Функции для работы с сессиями
# ------------------------------------------------------------------------------


def get_session() -> Session:
    """
    Возвращает новую сессию SQLAlchemy для ручного управления.
    Нужно закрывать её по окончании работы:

        db = get_session()
        try:
            # ... работа ...
        finally:
            db.close()

    Или используйте session_scope() для автоматического управления.
    """
    return SessionLocal()


@contextmanager
def session_scope() -> Generator[Session, None, None]:
    """
    Контекстный менеджер для безопасной работы с сессией:

        with session_scope() as db:
            # работа с db
            # по выходу commit или rollback

    При выходе:
    - если был Exception, делается rollback()
    - в любом случае закрывается сессия
    """
    session = get_session()
    try:
        yield session
        session.commit()
    except Exception as e:
        session.rollback()
        logger.exception("session_scope() rollback due to exception: %s", e)
        raise
    finally:
        session.close()

# ------------------------------------------------------------------------------
# init_db() - не рекомендуется в продакшене при использовании Alembic
# ------------------------------------------------------------------------------


def init_db() -> None:
    """
    Опциональная функция для локальной разработки или тестов,
    создаёт все таблицы (Base.metadata.create_all(bind=engine)).

    В продакшене при использовании Alembic полагайтесь на миграции!
    """
    logger.info("Initializing database schema... (create_all)")
    Base.metadata.create_all(bind=engine)
    logger.info("Database schema initialized.")

# ------------------------------------------------------------------------------
# health_check_db() - простой SELECT 1
# ------------------------------------------------------------------------------


def health_check_db() -> bool:
    """
    Простой тест доступности БД (SELECT 1).
    Возвращает True при успехе, иначе False.
    """
    try:
        with engine.connect() as connection:
            connection.execute("SELECT 1;")
        return True
    except SQLAlchemyError as e:
        logger.error("Database health check failed: %s", e)
        return False
