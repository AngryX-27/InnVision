# aggregator_service/aggregator_db/session.py

import os
import logging

from sqlalchemy import create_engine
from sqlalchemy.orm import (
    sessionmaker,
    scoped_session,
)

from aggregator_service.aggregator_db.models import Base

# NEW: Дополнительные импорты
from typing import Generator, Optional
from sqlalchemy.engine import Engine
from sqlalchemy.exc import OperationalError

logger = logging.getLogger(__name__)

###############################################################################
# 1. Считываем URL для подключения
#    Можно брать из .env или других конфигов (AGGREGATOR_DB_URL).
###############################################################################

DEFAULT_DB_URL = "postgresql://aggregator_user:aggregator_pass@aggregator_db:5432/aggregator_db"
DB_URL = os.getenv("AGGREGATOR_DB_URL", DEFAULT_DB_URL)

###############################################################################
# 2. Создаём движок (engine) SQLAlchemy с рекомендуемыми параметрами.
#    future=True (активирует часть «2.0 стиля»).
#    pool_pre_ping=True (проверяет соединение перед использованием).
###############################################################################

engine: Engine = create_engine(
    DB_URL,
    echo=False,            # Можно True, чтобы логировать все SQL-запросы
    future=True,
    pool_pre_ping=True,    # Проверка соединения
    pool_size=5,           # Размер пула (опционально, под вашу нагрузку)
    max_overflow=10,       # Сколько дополнительных подключений может быть
)

###############################################################################
# 3. Создаём фабрику сессий и scoped_session для потокобезопасности.
###############################################################################

SessionFactory = sessionmaker(
    autocommit=False,
    autoflush=False,
    bind=engine,
    future=True
)

aggregator_db_session = scoped_session(SessionFactory)
"""
scoped_session позволяет каждой нити (или другому контексту) 
использовать «свою» независимую сессию. Это упрощает многопоточную 
или многопроцессную работу с базой данных.
"""

###############################################################################
# 4. Функция для инициализации (создания) таблиц.
#    Если пользуетесь Alembic, можно не вызывать create_all,
#    а полагаться на миграции.
###############################################################################


def init_db() -> None:
    """
    Инициирует создание таблиц в базе данных, если их ещё нет.
    Использует Base.metadata.create_all(bind=engine).

    Рекомендуется для начальной разработки или тестовых окружений.
    Для продакшена лучше использовать миграции (например, Alembic).
    """
    logger.info("Инициализация базы, создание таблиц (если не существуют).")
    Base.metadata.create_all(bind=engine)

###############################################################################
# 5. Дополнительные методы (опционально),
#    если вы хотите аккуратно завершать сессию при завершении приложения.
###############################################################################


def close_db_session() -> None:
    """
    Закрывает scoped_session. Вызывайте при остановке приложения
    или завершении потока.

    scoped_session.remove():
    - «Отвязывает» сессию от текущего потока (или контекста),
    - При следующем обращении сессия будет создана заново.
    """
    logger.debug("Закрытие scoped_session для aggregator_db.")
    aggregator_db_session.remove()


def get_db() -> Generator[scoped_session, None, None]:
    """
    Типичный helper для фреймворков (Flask, FastAPI):
    отдаёт сессию (scoped_session), а по окончании запроса вызывает remove().

    Пример использования (FastAPI):
        @app.get("/items")
        def read_items(db=Depends(get_db)):
            ...
            return items
    """
    db = aggregator_db_session
    try:
        yield db
    finally:
        db.remove()

# ------------------------------------------------------------------------------
# NEW: Дополнительные улучшения
# ------------------------------------------------------------------------------


def close_db() -> None:
    """
    Шорткат (алиас) для close_db_session, чтобы можно было делать
    from aggregator_service.aggregator_db.session import init_db, close_db
    и не менять уже существующий код, который ссылается на close_db.
    """
    close_db_session()


def test_db_connection() -> bool:
    """
    Пробует сделать простейший запрос к базе, чтобы проверить подключение.
    Возвращает True, если запрос успешен, иначе False.

    Можно использовать, например, для проверок при старте приложения.
    """
    logger.debug("Проверка подключения к базе данных.")
    try:
        with engine.connect() as connection:
            connection.execute("SELECT 1")
        return True
    except OperationalError as e:
        logger.error(f"Ошибка подключения к базе: {e}")
        return False
