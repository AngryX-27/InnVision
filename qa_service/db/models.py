"""
qa_service/db/models.py
-----------------------
SQLAlchemy-модели (ORM) для хранения данных микросервиса QA Service.

Содержит:
  - QACheck: основная таблица для учёта результатов проверки (оригинальный текст, фильтрованный, ошибки, автокоррекция).
  - QAComment: вспомогательная таблица (лог/комментарии) к каждой проверке (опционально).
  - QACheckStatus (Enum): перечисление возможных статусов (pending, in_progress, completed, failed).

Использует:
  - SQLAlchemy
  - sqlalchemy.ext.mutable (MutableList/MutableDict) + PostgreSQL JSONB
  - Enum (для статусов)
  - created_at/updated_at для временных меток

Для создания таблиц (в локальной разработке) можно вызвать db.init_db(), но в продакшене 
рекомендуется Alembic для управления схемой БД.
"""

import datetime
from enum import Enum as PyEnum
from typing import Optional, List, Dict, Any

from sqlalchemy import (
    Column,
    Integer,
    String,
    Text,
    DateTime,
    Enum,
    ForeignKey,
    func
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.ext.mutable import MutableList, MutableDict
from sqlalchemy.orm import relationship

Base = declarative_base()

# ------------------------------------------------------------------------------
# Пример статуса проверки
# ------------------------------------------------------------------------------


class QACheckStatus(PyEnum):
    """Статусы, в которых может находиться проверка текста (QACheck)."""
    PENDING = "pending"       # ещё не обработан
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"   # успешно обработан
    # ошибка при обработке (напр. недоступен LanguageTool)
    FAILED = "failed"


# ------------------------------------------------------------------------------
# Модель QACheck – основная таблица
# ------------------------------------------------------------------------------
class QACheck(Base):
    """
    Основная таблица, где хранится результат проверки текста.

    Поля:
      - id: первичный ключ (int)
      - original_text: исходный текст
      - filtered_text: текст после фильтрации «плохих» слов
      - found_issues: JSONB (список найденных проблем, [{offset, error_text, suggestions}, ...])
      - corrected_text: автокорректированный текст (если применялась автокоррекция)
      - warnings: JSONB (список строк/сообщений, например ["Error GPT", "Auto-correct failed: ..."])
      - status: Enum(QACheckStatus) – текущее состояние
      - created_at, updated_at: временные метки
    """

    __tablename__ = "qa_checks"

    id = Column(Integer, primary_key=True, autoincrement=True)
    original_text = Column(Text, nullable=False,
                           doc="Исходный текст для проверки")
    filtered_text = Column(Text, nullable=False,
                           doc="Текст после фильтрации запрещённых слов")

    # JSONB для списка проблем (issues). Оборачиваем в MutableList,
    # чтобы SQLAlchemy автоматически отслеживал изменения (добавление/удаление).
    found_issues = Column(MutableList.as_mutable(
        JSONB), nullable=True, doc="Список найденных ошибок/проблем")

    corrected_text = Column(Text, nullable=True,
                            doc="Текст после автокоррекции (если применялась)")

    # warnings – тоже JSONB (список/массив). Например ["Auto-correct failed: ...", ...]
    warnings = Column(MutableList.as_mutable(JSONB),
                      nullable=True, doc="Список предупреждений/логов")

    status = Column(
        Enum(QACheckStatus, native_enum=False),
        default=QACheckStatus.PENDING,
        nullable=False,
        doc="Статус проверки (Enum)"
    )

    created_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
        doc="Время создания записи"
    )
    updated_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
        doc="Время последнего обновления записи"
    )

    # Пример связи с QAComment, если нужны «комментарии/логи» к проверке.
    comments = relationship(
        "QAComment",
        back_populates="qa_check",
        cascade="all, delete-orphan",
    )

    def __repr__(self) -> str:
        return (f"<QACheck id={self.id}, status={self.status.value}, "
                f"created_at={self.created_at}, updated_at={self.updated_at}>")


# ------------------------------------------------------------------------------
# Модель QAComment – дополнительная таблица
# ------------------------------------------------------------------------------
class QAComment(Base):
    """
    Дополнительная таблица для хранения комментариев или лог-записей,
    привязанных к конкретной проверке (QACheck).

    Поля:
      - id: первичный ключ
      - qa_check_id: внешний ключ на QACheck
      - comment_text: содержимое комментария/лога
      - created_at: временная метка

    Связь: QAComment -> QACheck (qa_check_id)
    """

    __tablename__ = "qa_comments"

    id = Column(Integer, primary_key=True, autoincrement=True)
    qa_check_id = Column(Integer, ForeignKey(
        "qa_checks.id", ondelete="CASCADE"), nullable=False)

    comment_text = Column(Text, nullable=False,
                          doc="Содержимое комментария/лога")

    created_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
        doc="Время создания комментария"
    )

    qa_check = relationship(
        "QACheck",
        back_populates="comments",
    )

    def __repr__(self) -> str:
        return f"<QAComment id={self.id}, qa_check_id={self.qa_check_id}, created_at={self.created_at}>"


# ------------------------------------------------------------------------------
# (Опционально) Пример дополнительной сущности (ChangeLog) – если нужно
# ------------------------------------------------------------------------------
# class QAChangeLog(Base):
#     """
#     Таблица для хранения истории изменений проверок (например, кто/когда поменял статус).
#     Это пример: при необходимости можно хранить «отладочную» инфу.
#     """
#     __tablename__ = "qa_changelog"
#
#     id = Column(Integer, primary_key=True, autoincrement=True)
#     qa_check_id = Column(Integer, ForeignKey("qa_checks.id", ondelete="CASCADE"), nullable=False)
#     action = Column(String(100), nullable=False, doc="Тип действия (e.g. 'update_status', 'add_comment', etc.)")
#     details = Column(MutableDict.as_mutable(JSONB), nullable=True, doc="Дополнительные детали действия")
#     timestamp = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
#
#     # Связь на QACheck
#     qa_check = relationship("QACheck", backref="changelog")
#
#     def __repr__(self):
#         return f"<QAChangeLog id={self.id}, check_id={self.qa_check_id}, action={self.action}, timestamp={self.timestamp}>"
