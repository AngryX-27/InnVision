"""
2025_02_10_1300_create_tz_documents

Создаёт схему tz и таблицу tz.tz_documents
для хранения TЗ (Task Documents) в JSONB.
Добавляет GIN-индекс для ускоренного поиска по data.
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# Идентификаторы ревизии
revision = "202502101300"
# <-- Замените на реальный идентификатор вашей предыдущей миграции
down_revision = "e1e339aeeea5"
branch_labels = None
depends_on = None


def upgrade():
    # 1) Создаём схему tz (если не существует)
    op.execute("CREATE SCHEMA IF NOT EXISTS tz")

    # 2) Создаём таблицу tz.tz_documents
    op.create_table(
        "tz_documents",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("order_id", sa.Text(), unique=True),
        sa.Column("data", postgresql.JSONB(
            astext_type=sa.Text()), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.text("NOW()")),
        sa.Column("updated_at", sa.DateTime(timezone=True),
                  server_default=sa.text("NOW()")),
        schema="tz"
    )

    # 3) Создаём GIN-индекс по data, чтобы быстро искать по JSONB
    op.create_index(
        "ix_tz_documents_data_gin",
        "tz_documents",
        [sa.text("data")],  # указываем поле
        postgresql_using="gin",
        schema="tz"
    )

    # (Опционально) Если хотите задать триггер для auto-update updated_at на уровне SQL:
    # Postgres не обновит updated_at автоматически при UPDATE,
    # обычно это делается на уровне ORM (onupdate=func.now()).
    # Но если нужно триггер на SQL-уровне, можно сделать (раскомментируйте):
    #
    # op.execute("""
    # CREATE OR REPLACE FUNCTION tz.update_timestamp()
    # RETURNS TRIGGER AS $$
    # BEGIN
    #   NEW.updated_at = NOW();
    #   RETURN NEW;
    # END;
    # $$ language 'plpgsql';
    #
    # CREATE TRIGGER update_tz_documents_updated_at
    # BEFORE UPDATE ON tz.tz_documents
    # FOR EACH ROW
    # EXECUTE PROCEDURE tz.update_timestamp();
    # """)


def downgrade():
    # Откат: удаляем индекс, таблицу и схему (аккуратно)
    op.drop_index("ix_tz_documents_data_gin",
                  table_name="tz_documents", schema="tz")

    op.drop_table("tz_documents", schema="tz")
    op.execute("DROP SCHEMA IF EXISTS tz CASCADE")
