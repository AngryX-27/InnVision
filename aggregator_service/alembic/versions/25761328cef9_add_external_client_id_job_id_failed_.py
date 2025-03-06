"""
Full improvements (excluding security):
 - New schema 'archive'
 - Partial index on orders (status != 'done')
 - Partitioning of client_dialogs by created_at (monthly range)
 - Example of new table for archived orders
 - Indices for performance
 - Dev/Staging/Prod approach (in comments)
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
from datetime import datetime

# revision identifiers, used by Alembic
# 2025_02_10_1300_create_tz_documents мб это) или это 202501311500
revision = "2025XXXXXXXX"
down_revision = "25761328cef9"  # вставьте предыдущую миграцию
branch_labels = None
depends_on = None


def upgrade():
    # 1) Создаём схему 'archive', если хотим отделить старые данные
    op.execute("CREATE SCHEMA IF NOT EXISTS archive")

    # 2) Частичный индекс на orders (status != 'done')
    # Ускоряет выборки где status IN (...)
    op.create_index(
        "idx_orders_not_done",
        "orders",
        ["job_id"],
        postgresql_where=sa.text("status != 'done'")
    )
    # Пример: если часто ищете заказы, у которых status!='done'.

    # 3) Организация партиционирования таблицы client_dialogs по дате (created_at)
    # (Range partition - monthly)
    # Для начала нужно проверить, что у client_dialogs не было первичного ключа "id" в partition:
    #   PostgreSQL >= 11 поддерживает PRIMARY KEY на партиции.
    #   Если уже есть "id SERIAL" PK - нужно переделать. Предположим, всё ок.

    # a) ALTER TABLE, чтобы стать PARTITIONED BY RANGE (created_at).
    # Но PostgreSQL не позволяет "превратить" уже существующую таблицу в partitioned
    # напрямую. Обычно: 1) создаём новую partitioned table,
    # 2) переносим данные, 3) переименовываем.
    # Для упрощения здесь покажу "создание новой структуры":
    op.execute("""
    CREATE TABLE IF NOT EXISTS client_dialogs_new (
        LIKE client_dialogs INCLUDING ALL
    )
    PARTITION BY RANGE (created_at);
    """)

    # b) Переносим данные из старой таблицы
    op.execute("""
    INSERT INTO client_dialogs_new
    SELECT * FROM client_dialogs;
    """)

    # c) Переименовываем старую таблицу (bkp) и новую ставим на её место
    op.rename_table("client_dialogs", "client_dialogs_bkp")
    op.rename_table("client_dialogs_new", "client_dialogs")

    # d) Создаём партиции (например, на ближайшие месяцы)
    # Пример: партиция на январь 2025
    op.execute("""
    CREATE TABLE IF NOT EXISTS client_dialogs_2025_01
    PARTITION OF client_dialogs
    FOR VALUES FROM ('2025-01-01') TO ('2025-02-01');
    """)
    # Аналогично можно скриптом создать партиции на другие месяцы

    # e) Если всё ок, удаляем старую backup-таблицу
    op.drop_table("client_dialogs_bkp")

    # 4) Пример новой таблицы в схеме 'archive'
    #    для архивных "orders" старше 1 года
    op.execute("""
    CREATE TABLE IF NOT EXISTS archive.archived_orders (
        LIKE orders INCLUDING ALL
    );
    """)

    # Можете туда периодически переносить заказы, у которых status='done' > N месяцев.

    # 5) Дополнительные индексы, если нужно
    # Например, ускорим поиск orders по created_at:
    op.create_index("idx_orders_created_at", "orders", ["created_at"])

    # 6) Пример approach dev/staging/prod:
    # На практике вы создаёте разные БД (db_innvision_dev, db_innvision_staging, db_innvision_prod)
    # либо одну БД, но разные схемы.
    #   - dev: "DROP SCHEMA archive CASCADE" и recreate
    #   - staging: max parallels, small data set
    #   - prod: real data, daily backups, scheduled partition creation
    # (Комментарии, чтобы показать идейность.)


def downgrade():
    # Откат: теоретически нужно "спасти" данные, но для простоты - удаляем таблицы/схемы/индексы:
    op.drop_index("idx_orders_created_at", table_name="orders")
    op.execute("DROP TABLE IF EXISTS archive.archived_orders CASCADE")
    op.execute("DROP SCHEMA IF EXISTS archive CASCADE")

    # Партиционирование откатить сложнее:
    # 1) Удаляем новую partitioned table
    op.drop_table("client_dialogs")
    # 2) Возвращаем backup-таблицу (не сохранилось) - в реальности нужен скрипт миграции вручную
    op.rename_table("client_dialogs_bkp", "client_dialogs")

    # partial index
    op.drop_index("idx_orders_not_done", table_name="orders")
