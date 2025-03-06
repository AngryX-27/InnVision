"""
env.py - Alembic (Расширенный, "продвинутый")

Использует движок (engine) из aggregator_service.db
и метаданные (Base.metadata), чтобы выполнять миграции.
Добавлены:
 - include_object (фильтр объектов)
 - compare_index=True (автогенерация миграций для индексов)
 - Вывод SQL в файл при offline-режиме
 - version_table="my_alembic_version"
"""

import os
from logging.config import fileConfig

from alembic import context
from aggregator_service.db import engine, Base

# Alembic Config object
config = context.config

# Читаем настройки логирования из alembic.ini
fileConfig(config.config_file_name)

# Метаданные всех моделей
target_metadata = Base.metadata

# Ключевые параметры для автогенерации
alembic_compare_kwargs = {
    "compare_type": True,             # сравнивать изменения типов столбцов
    "compare_server_default": True,   # сравнивать server_default
    "compare_index": True,            # сравнивать индексы
}

# Примерная фильтрация: пропускаем некоторые таблицы


def include_object(object_, name, type_, reflected, compare_to):
    """
    Возвращает True, если объект нужно включить в миграцию.
    Возвращает False, если нужно пропустить.
    """
    # Пропустим таблицу "old_logs" (пример)
    if type_ == "table" and name == "old_logs":
        return False

    # Alembic сам пропустит свою служебную "alembic_version"
    # (но можно явно прописать if name == "alembic_version": return False)

    return True


def run_migrations_offline():
    """
    Миграции в offline-режиме (генерация SQL без подключения к БД).
    """
    # Если alembic.ini не указал sqlalchemy.url, пытаемся взять из engine.url
    url = config.get_main_option("sqlalchemy.url")
    if not url:
        url = str(engine.url)

    # Для демонстрации: пишем результирующий SQL в файл (если хотим)
    offline_sql_path = os.getenv(
        "ALEMBIC_OFFLINE_SQL_PATH", "offline_migrations.sql")

    with open(offline_sql_path, "w", encoding="utf-8") as buf:
        context.configure(
            url=url,
            target_metadata=target_metadata,
            literal_binds=True,
            output_buffer=buf,             # сохраняем SQL в файл
            version_table="my_alembic_version",  # меняем имя таблицы версий
            include_object=include_object,
            **alembic_compare_kwargs,
            dialect_opts={"paramstyle": "named"},
        )

        with context.begin_transaction():
            context.run_migrations()

    print(f"[Alembic] Offline migration SQL записан в: {offline_sql_path}")


def run_migrations_online():
    """
    Миграции в online-режиме (подключаемся к БД и изменяем).
    """
    with engine.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            version_table="my_alembic_version",  # имя таблицы версий
            include_object=include_object,
            **alembic_compare_kwargs
        )

        with context.begin_transaction():
            context.run_migrations()


# Проверяем режим
if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
