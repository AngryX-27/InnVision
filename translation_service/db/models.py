"""
models.py (db/models.py)

Содержит SQLAlchemy ORM-модели (таблицы) для микросервисной системы:
1) Aggregator (orders, client dialogs)
2) Translation Service (glossary, forbidden words, translation memory)

Дополнения и улучшения:
- Расширенные поля в Orders (due_date, client_id, payment_status, assigned_to).
- Модель OrdersHistory (для аудита изменения статусов).
- Хэширование длинного исходного текста в TranslationMemory (hash_text).
- Уникальные индексы, новые связи.
- Перенесена логика Enums (OrderStatus) в native PostgreSQL Enum (пример).
- Пример «PaymentStatus» (если нужен).
"""

import enum
import hashlib
from datetime import datetime
from sqlalchemy import (
    Column, Integer, String, Text, DateTime, func,
    ForeignKey, Enum, Boolean, Index, Float, LargeBinary
)
from sqlalchemy.orm import relationship, declarative_base
from sqlalchemy.sql import text
from sqlalchemy.ext.mutable import MutableDict  # если нужен JSON-столбец
from sqlalchemy.dialects.postgresql import JSONB  # либо JSONB

Base = declarative_base()

##############################
# Пример enum для статусов заказа (native_enum=True)
##############################


class OrderStatus(str, enum.Enum):
    new = "new"
    confirmed = "confirmed"
    in_progress = "in_progress"
    qa = "qa"
    done = "done"
    failed = "failed"
    retry = "retry"

# Допустим, статусы оплаты (пример):


class PaymentStatus(str, enum.Enum):
    unpaid = "unpaid"
    paid = "paid"
    refunded = "refunded"

##############################
# 1) Модель Orders (для агрегатора)
##############################


class Orders(Base):
    """
    Таблица 'orders' — хранение заказов (например, на перевод или генерацию текста).
    Теперь расширена дополнительными полями:
    - client_id (FK на Users или другую модель)
    - due_date (срок)
    - payment_status
    - assigned_to (кто отвечает за заказ)
    - price (Float), currency (String(3)) 
    """
    __tablename__ = "orders"

    id = Column(Integer, primary_key=True, index=True)

    title = Column(String(200), nullable=True, index=True,
                   doc="Короткое название заказа")
    description = Column(Text, nullable=True, doc="Описание заказа, детали")

    # Enum-статус (native_enum=True), чтобы PostgreSQL создавал собственный enum
    status = Column(Enum(OrderStatus, native_enum=True),
                    default=OrderStatus.new, nullable=False, index=True)

    # Дополнительные поля
    client_id = Column(Integer, nullable=True,
                       doc="FK на пользователя, если есть таблица users")
    assigned_to = Column(Integer, nullable=True,
                         doc="ID сотрудника, ответственного за заказ (пример)")

    # Срок сдачи
    due_date = Column(DateTime(timezone=True), nullable=True,
                      doc="Крайний срок выполнения")

    # Оплата
    price = Column(Float, nullable=True, doc="Цена выполнения заказа")
    currency = Column(String(3), nullable=True,
                      doc="Валюта (USD, EUR, RUB, ...)")
    payment_status = Column(Enum(PaymentStatus, native_enum=True),
                            default=PaymentStatus.unpaid, doc="Статус оплаты")

    # Даты
    created_at = Column(DateTime(timezone=True),
                        server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    # Связь с переписками (ClientDialogs)
    dialogs = relationship(
        "ClientDialogs",
        back_populates="order",
        cascade="all, delete-orphan"
    )

    def __repr__(self):
        return f"<Orders id={self.id}, status={self.status}, title={self.title}>"

##############################
# 2) Модель ClientDialogs (переписка с клиентами)
##############################


class ClientDialogs(Base):
    """
    Таблица 'client_dialogs' — хранит историю сообщений и переписок
    по конкретному заказу (Orders). 
    """
    __tablename__ = "client_dialogs"

    id = Column(Integer, primary_key=True, index=True)
    order_id = Column(Integer, ForeignKey(
        "orders.id", ondelete="CASCADE"), nullable=False, index=True)
    role = Column(String(50), nullable=False,
                  doc="Чья реплика: client, system, manager и т.д.")
    message = Column(Text, nullable=False, doc="Текст сообщения")

    # Чтобы быстро сортировать по времени:
    timestamp = Column(DateTime(timezone=True),
                       server_default=func.now(), nullable=False)

    # Связь обратно к Orders
    order = relationship("Orders", back_populates="dialogs")

    def __repr__(self):
        return f"<ClientDialogs id={self.id}, order_id={self.order_id}, role={self.role}>"

##############################
# 3) Модель GlossaryTerm (глоссарий)
##############################


class GlossaryTerm(Base):
    """
    Таблица 'glossary_terms' — хранит термины и их переводы.
    Расширена: subdomain, уникальный индекс
    """
    __tablename__ = "glossary_terms"

    id = Column(Integer, primary_key=True, index=True)
    source_lang = Column(String(10), nullable=False,
                         doc="Исходный язык, напр. 'en', 'ru'")
    target_lang = Column(String(10), nullable=False,
                         doc="Целевой язык, напр. 'en', 'ru'")
    term_source = Column(String(255), nullable=False, doc="Термин-исходник")
    term_target = Column(String(255), nullable=False, doc="Термин-перевод")
    domain = Column(String(50), nullable=True,
                    doc="Сфера (IT, legal, marketing)")
    subdomain = Column(String(50), nullable=True, doc="Подсфера (пример)")

    created_at = Column(DateTime(timezone=True),
                        server_default=func.now(), nullable=False)

    __table_args__ = (
        Index("idx_glossary_langs", "source_lang", "target_lang"),
        Index("uix_glossary_unique", "source_lang",
              "target_lang", "term_source", "domain", unique=True)
    )

    def __repr__(self):
        return f"<GlossaryTerm id={self.id}, {self.source_lang}->{self.target_lang}, {self.term_source}>"

##############################
# 4) Модель ForbiddenWord (запрещённые слова)
##############################


class ForbiddenWord(Base):
    """
    Таблица 'forbidden_words' — хранит перечень слов/фраз (возможно с lang),
    причину запрета.
    """
    __tablename__ = "forbidden_words"

    id = Column(Integer, primary_key=True, index=True)
    word = Column(String(255), nullable=False, doc="Запрещённое слово/фраза")
    lang = Column(String(10), nullable=True,
                  doc="Если нужно хранить язык слова")
    reason = Column(Text, nullable=True, doc="Причина (необязательно)")

    created_at = Column(DateTime(timezone=True),
                        server_default=func.now(), nullable=False)

    # Уникальный индекс, если слово+lang должны быть уникальными
    __table_args__ = (
        Index("uix_forbidden_lang_word", "lang", "word", unique=True),
    )

    def __repr__(self):
        return f"<ForbiddenWord id={self.id}, word={self.word}, lang={self.lang}>"

##############################
# 5) Модель TranslationMemory (память переводов)
##############################


class TranslationMemory(Base):
    """
    Кэш (или память) уже выполненных переводов.
    Добавлен хэш (hash_text), чтобы не сравнивать длинные тексты напрямую.
    """
    __tablename__ = "translation_memory"

    id = Column(Integer, primary_key=True, index=True)
    source_lang = Column(String(10), nullable=False,
                         doc="Исходный язык ('en')")
    target_lang = Column(String(10), nullable=False, doc="Целевой язык ('ru')")

    # Для длинных текстов. Можно хранить md5/sha256
    hash_text = Column(String(64), nullable=False,
                       doc="Хеш исходного текста (sha256)")

    source_text = Column(Text, nullable=False, doc="Полный исходный текст")
    translated_text = Column(Text, nullable=False, doc="Результат перевода")

    created_at = Column(DateTime(timezone=True),
                        server_default=func.now(), nullable=False)

    __table_args__ = (
        Index("idx_tm_src_tgt", "source_lang", "target_lang"),
        Index("uix_tm_hash_text", "source_lang",
              "target_lang", "hash_text", unique=True),
    )

    def __repr__(self):
        text_preview = (
            self.source_text[:30] + "...") if len(self.source_text) > 30 else self.source_text
        return f"<TranslationMemory id={self.id}, src_lang={self.source_lang}, tgt_lang={self.target_lang}, text={text_preview}>"

    @staticmethod
    def compute_hash(text: str) -> str:
        """
        Вычисляем sha256 от исходного текста.
        """
        return hashlib.sha256(text.encode("utf-8")).hexdigest()

##############################
# 6) Доп. модель OrdersHistory (пример аудита)
##############################


class OrdersHistory(Base):
    """
    Таблица 'orders_history' — хранит историю изменения статусов заказов, 
    записывая (old_status, new_status, changed_at).
    Можно расширить для аудита цены, assigned_to и т.д.
    """
    __tablename__ = "orders_history"

    id = Column(Integer, primary_key=True, index=True)
    order_id = Column(Integer, ForeignKey(
        "orders.id", ondelete="CASCADE"), nullable=False, index=True)
    old_status = Column(Enum(OrderStatus, native_enum=True), nullable=True)
    new_status = Column(Enum(OrderStatus, native_enum=True), nullable=False)
    changed_at = Column(DateTime(timezone=True),
                        server_default=func.now(), nullable=False)

    # Если нужно знать, кто изменил статус
    changed_by = Column(Integer, nullable=True,
                        doc="ID сотрудника/пользователя, изменившего статус")

    def __repr__(self):
        return f"<OrdersHistory order_id={self.order_id}, old={self.old_status}, new={self.new_status}>"

##############################
# 7) Создание таблиц (Alembic)
##############################
# Обычно вы используете Alembic.
# При старте приложения можно вызвать:
# from sqlalchemy import create_engine
# engine = create_engine("postgresql://user:pass@host:5432/db_name")
# Base.metadata.create_all(bind=engine)
#
# Но лучше Alembic / migrations для управления схемой.
