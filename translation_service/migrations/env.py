"""
env.py — основной скрипт Alembic, управляющий миграциями.

Основные моменты:
1) Читаем DB_URL из config.py (или окружения), а не из alembic.ini.
2) Импортируем Base из db.models, чтобы Alembic «видел» модели.
3) Реализуем offline/online режим.
4) Дополнительно можно фильтровать таблицы, обрабатывать исключения и т.п.
"""

from translation_service.db.models import Base
import os
import sys
from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool
from sqlalchemy import create_engine
from sqlalchemy.engine import Connection

# 1) Читаем alembic.ini для базовой конфигурации логирования
config = context.config

# Настройка логирования Alembic (если у вас прописан [logging] в alembic.ini)
fileConfig(config.config_file_name)

# 2) Импортируем ваш config.py (где DB_URL)
# Если у вас иной путь/название, замените
try:
    from translation_service.config import settings
except ImportError:
    # fallback, если нет config.py
    settings = None

# 3) Импортируем вашу базу (Base) из db.models, чтобы Alembic «видел» таблицы
# Пример: from translation_service.db.models import Base
# Или from db.models import Base

# 4) Указываем метаданные (для автогенерации)
target_metadata = Base.metadata

# 5) Считываем строку подключения (DB_URL) из settings.DB_URL, если доступна
# При желании можно fallback на config.get_main_option("sqlalchemy.url")
DB_URL = None
if settings and hasattr(settings, "DB_URL"):
    DB_URL = settings.DB_URL
    # Запишем в конфиг Alembic (чтобы engine_from_config мог видеть), но
    # обычно указывают prefix="sqlalchemy."
    config.set_main_option("sqlalchemy.url", DB_URL)
else:
    # fallback: берем из alembic.ini (если прописано)
    DB_URL = config.get_main_option("sqlalchemy.url")


def run_migrations_offline() -> None:
    """
    Запуск миграций в «offline»-режиме.

    В offline-режиме Alembic генерирует SQL, не подключаясь к БД.
    """
    url = DB_URL
    if not url:
        raise RuntimeError("Не удалось определить DB_URL для offline-режима.")

    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        compare_type=True,  # при автогенерации изменений типов столбцов
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """
    Запуск миграций в «online»-режиме: реальное подключение к БД,
    транзакции Alembic для внесения изменений.
    """
    url = DB_URL
    if not url:
        raise RuntimeError("Не удалось определить DB_URL для online-режима.")

    # Можно напрямую создать движок:
    connectable = create_engine(
        url,
        poolclass=pool.NullPool
    )
    # Или engine_from_config, но тогда нужно прописать
    # prefix="sqlalchemy." в set_main_option(...) и в alembic.ini.

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,       # Учитывать изменения типов
            compare_server_default=True,  # Если нужны изменения дефолтов
            # version_table='alembic_version',  # при желании кастомизируем
        )

        with context.begin_transaction():
            context.run_migrations()


# Главная точка входа
if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
