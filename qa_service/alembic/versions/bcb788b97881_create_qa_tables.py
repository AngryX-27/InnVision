"""Create QA tables

Revision ID: bcb788b97881
Revises:
Create Date: 2025-02-15 10:23:00
"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = 'bcb788b97881'
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    """
    Пример «боевой» миграции для QA Service:
    1) Создаём таблицу пользователей (qa_users)
    2) Создаём таблицу тестовых кейсов (qa_testcases)
    3) Создаём таблицу результатов (qa_results), ссылающуюся на пользователей и тестовые кейсы
    4) Добавляем индексы и уникальные ключи, где необходимо
    """

    # 1) Таблица пользователей (qa_users)
    #    - id: первичный ключ
    #    - username: строка, индексированная и уникальная
    #    - created_at: дата/время создания аккаунта
    op.create_table(
        'qa_users',
        sa.Column('id', sa.Integer, primary_key=True, autoincrement=True),
        sa.Column('username', sa.String(50), nullable=False),
        sa.Column('email', sa.String(100), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
    )
    # Дополнительный индекс: имя пользователя уникально
    op.create_unique_constraint(
        'uq_qa_users_username', 'qa_users', ['username'])
    # Индексируем email для быстрого поиска (необязательно уникальный)
    op.create_index('ix_qa_users_email', 'qa_users', ['email'])

    # 2) Таблица тестовых кейсов (qa_testcases)
    #    - id: первичный ключ
    #    - title, description: основные поля
    #    - author_id: внешний ключ на qa_users
    #    - is_active: флажок, по умолчанию True
    op.create_table(
        'qa_testcases',
        sa.Column('id', sa.Integer, primary_key=True, autoincrement=True),
        sa.Column('title', sa.String(200), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('author_id', sa.Integer, sa.ForeignKey(
            'qa_users.id', ondelete='CASCADE'), nullable=False),
        sa.Column('is_active', sa.Boolean(),
                  server_default=sa.text('TRUE'), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
    )
    # Индексируем title для быстрого поиска
    op.create_index('ix_qa_testcases_title', 'qa_testcases', ['title'])

    # 3) Таблица результатов (qa_results)
    #    - id: первичный ключ
    #    - testcase_id: внешний ключ на qa_testcases
    #    - user_id: внешний ключ на qa_users (кто выполнял тест)
    #    - status: результат (PASSED / FAILED / SKIPPED / и т.д.)
    #    - executed_at: время выполнения
    op.create_table(
        'qa_results',
        sa.Column('id', sa.Integer, primary_key=True, autoincrement=True),
        sa.Column('testcase_id', sa.Integer, sa.ForeignKey(
            'qa_testcases.id', ondelete='CASCADE'), nullable=False),
        sa.Column('user_id', sa.Integer, sa.ForeignKey(
            'qa_users.id', ondelete='SET NULL'), nullable=True),
        sa.Column('status', sa.String(50), nullable=False),
        sa.Column('executed_at', sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
    )
    # Индекс по (testcase_id, user_id) для аналитики
    op.create_index('ix_qa_results_testcase_user',
                    'qa_results', ['testcase_id', 'user_id'])


def downgrade():
    """
    Откат миграции (downgrade):
    1) Удаляем таблицу результатов
    2) Удаляем таблицу тестовых кейсов
    3) Удаляем таблицу пользователей
    """
    # При откате операции должны идти в обратном порядке
    op.drop_index('ix_qa_results_testcase_user', table_name='qa_results')
    op.drop_table('qa_results')

    op.drop_index('ix_qa_testcases_title', table_name='qa_testcases')
    op.drop_table('qa_testcases')

    op.drop_index('ix_qa_users_email', table_name='qa_users')
    op.drop_constraint('uq_qa_users_username', 'qa_users', type_='unique')
    op.drop_table('qa_users')
