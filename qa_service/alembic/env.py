import os
from alembic import context
from sqlalchemy import engine_from_config, pool

config = context.config

# Можно переопределить url из ENV:
db_url = os.getenv("QA_DB_URL")
if db_url:
    config.set_main_option("sqlalchemy.url", db_url)

target_metadata = None  # или импорт вашей модели (если автоген)


def run_migrations_offline():
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url, target_metadata=target_metadata, literal_binds=True)
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online():
    connectable = engine_from_config(
        config.get_section(config.config_ini_section),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(connection=connection,
                          target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()
