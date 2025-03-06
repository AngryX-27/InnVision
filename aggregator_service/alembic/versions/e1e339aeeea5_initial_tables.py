"""
Improvements after initial tables:
 - Add updated_at in orders/client_dialogs
 - Convert orders.status from String(50) to Enum
 - Add job_id in orders (unique, index)
 - Cascade delete for client_dialogs FK
 - Partial index for orders where status != 'done'
 - server_default=func.now() for created_at/updated_at
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql
from sqlalchemy.sql import func


# revision identifiers
revision = "202501311500"
down_revision = "e1e339aeeea5"  # ссылка на вашу "initial_tables" миграцию
branch_labels = None
depends_on = None


def upgrade():
    # 1) Добавляем поле updated_at в orders:
    op.add_column(
        "orders",
        sa.Column(
            "updated_at",
            sa.DateTime(),
            server_default=sa.text("CURRENT_TIMESTAMP"),  # для совместимости
            nullable=True
        )
    )
    # Чтобы при обновлении ORM-объекта тоже обновлялось,
    # позднее на уровне Python можно прописать onupdate=func.now().

    # А также уточним, чтобы created_at имел server_default=now()
    # (в initial_tables не было server_default)
    op.alter_column(
        "orders",
        "created_at",
        server_default=sa.text("CURRENT_TIMESTAMP")
    )

    # 2) Перевести orders.status на Enum

    # а) Создаём тип Enum в PostgreSQL (для MySQL/SQLite можно иначе)
    # Задаём названия статусов: new, negotiation, agreed, in_progress, done, closed, failed
    status_enum = postgresql.ENUM(
        "new", "negotiation", "agreed", "in_progress", "done", "closed", "failed",
        name="order_status_enum"
    )
    status_enum.create(op.get_bind(), checkfirst=True)

    # б) ALTER COLUMN с String(50) на новый тип Enum
    op.alter_column(
        "orders",
        "status",
        existing_type=sa.String(length=50),
        type_=status_enum,
        postgresql_using="status::order_status_enum",  # каст старого значения
        existing_nullable=True  # исходно поле nullable
    )

    # в) Если хотите, установите default='new'
    op.execute("ALTER TABLE orders ALTER COLUMN status SET DEFAULT 'new'")

    # 3) Добавляем поле job_id (уникальный идентификатор)
    op.add_column(
        "orders",
        sa.Column("job_id", sa.String(255), nullable=True)
    )
    # Добавляем unique-индекс на job_id (если логика требует уникальности)
    op.create_unique_constraint("uq_orders_job_id", "orders", ["job_id"])
    # Или если хотите просто индекс без unique:
    # op.create_index("ix_orders_job_id", "orders", ["job_id"], unique=False)

    # 4) Добавить cascade delete в client_dialogs.order_id
    # 4.1) Удаляем старый FK
    op.drop_constraint("client_dialogs_order_id_fkey",
                       "client_dialogs", type_="foreignkey")

    # 4.2) Создаём новый FK with ondelete='CASCADE'
    op.create_foreign_key(
        "client_dialogs_order_id_fkey",
        "client_dialogs", "orders",
        ["order_id"], ["id"],
        ondelete="CASCADE"
    )

    # 4.3) Также добавим updated_at в client_dialogs
    op.add_column(
        "client_dialogs",
        sa.Column(
            "updated_at",
            sa.DateTime(),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=True
        )
    )
    op.alter_column(
        "client_dialogs",
        "created_at",
        server_default=sa.text("CURRENT_TIMESTAMP")
    )

    # 5) Частичный индекс для "активных" заказов, где status != 'done'
    # PostgreSQL partial index:
    op.create_index(
        "idx_orders_active_status",
        "orders",
        ["id"],  # или ["job_id"], "created_at" - зависит от запроса,
        postgresql_where=sa.text("status != 'done'")
    )


def downgrade():
    # ОТКАТ

    # 5) Удаляем частичный индекс
    op.drop_index("idx_orders_active_status", table_name="orders")

    # 4.3) Удаляем updated_at из client_dialogs (и сброс server_default)
    op.drop_column("client_dialogs", "updated_at")
    op.alter_column("client_dialogs", "created_at", server_default=None)

    # 4.2) Удаляем новый FK, возвращаем старый
    op.drop_constraint("client_dialogs_order_id_fkey",
                       "client_dialogs", type_="foreignkey")
    op.create_foreign_key(
        "client_dialogs_order_id_fkey",
        "client_dialogs", "orders",
        ["order_id"], ["id"]  # без ondelete
    )

    # 3) Удаляем job_id + UniqueConstraint
    op.drop_constraint("uq_orders_job_id", "orders", type_="unique")
    op.drop_column("orders", "job_id")

    # 2) Откат Enum => String(50)
    status_enum = postgresql.ENUM(
        "new", "negotiation", "agreed", "in_progress", "done", "closed", "failed",
        name="order_status_enum"
    )
    op.alter_column(
        "orders",
        "status",
        existing_type=status_enum,
        type_=sa.String(50),
        postgresql_using="status::text"
    )
    status_enum.drop(op.get_bind())  # удаляем тип

    op.execute("ALTER TABLE orders ALTER COLUMN status DROP DEFAULT")

    # 1) Удаляем updated_at из orders
    # убираем default для created_at
    op.alter_column("orders", "created_at", server_default=None)
    op.drop_column("orders", "updated_at")
