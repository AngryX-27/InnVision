# aggregator_service/models.py

from datetime import datetime
import enum

from sqlalchemy import (
    Column,
    Integer,
    String,
    Float,
    Boolean,
    DateTime,
    ForeignKey,
    Text,
    Enum as SAEnum,
    Index
)
from sqlalchemy.sql import func
from sqlalchemy.orm import relationship, declarative_base

# Создаём базовый класс для моделей
Base = declarative_base()


class OrderStatusEnum(enum.Enum):
    """Перечисление для поля Order.status."""
    new = "new"
    negotiation = "negotiation"
    agreed = "agreed"
    in_progress = "in_progress"
    done = "done"
    closed = "closed"
    failed = "failed"


class Order(Base):
    """
    Модель, соответствующая таблице 'orders'.

    Хранит основные данные о заказе:
    - topic (тема)
    - language (язык)
    - status (Enum: new, negotiation, agreed, in_progress, done, closed, failed)
    - client_name, price, is_urgent
    - external_client_id, job_id
    - created_at / updated_at
    - dialogs (один-ко-многим) с ClientDialog (order_id).

    Дополнительно можно хранить приоритет, дополнительные метаданные и т. д.
    """
    __tablename__ = "orders"

    # Пример расширенной настройки таблицы: Индексы и т.п.
    __table_args__ = (
        # Индекс на status (часто фильтруем по статусу)
        Index("ix_orders_status", "status"),
    )

    id = Column(Integer, primary_key=True, index=True)
    topic = Column(String(255), nullable=False)
    language = Column(String(50), nullable=False)

    status = Column(
        SAEnum(OrderStatusEnum, name="order_status_enum"),
        default=OrderStatusEnum.new,
        nullable=False
    )

    created_at = Column(
        DateTime(timezone=True),
        server_default=func.now()
    )
    updated_at = Column(
        DateTime(timezone=True),
        onupdate=func.now(),
        server_default=func.now()
    )

    client_name = Column(String(255), nullable=True)
    price = Column(Float, nullable=True)
    is_urgent = Column(Boolean, default=False)

    external_client_id = Column(String(255), nullable=True)
    job_id = Column(String(255), nullable=True, unique=True, index=True)

    dialogs = relationship(
        "ClientDialog",
        back_populates="order",
        cascade="all, delete-orphan"
    )

    def __repr__(self):
        return (
            f"<Order id={self.id} "
            f"status={self.status.value if self.status else None} "
            f"topic={self.topic} "
            f"created_at={self.created_at}>"
        )


class ClientDialog(Base):
    """
    Модель для таблицы 'client_dialogs'.

    Хранит сообщения (role, message) для конкретного заказа:
    - order_id: связь с Order
    - role: 'system', 'assistant', 'user'
    - message: текст (Text)
    - message_type: 'text', 'file', и т.д.
    - created_at / updated_at

    Полезно для логирования всей переписки с клиентом.
    """
    __tablename__ = "client_dialogs"

    __table_args__ = (
        # Например, если будем часто фильтровать по role
        Index("ix_client_dialogs_role", "role"),
    )

    id = Column(Integer, primary_key=True, index=True)
    order_id = Column(
        Integer,
        ForeignKey("orders.id", ondelete="CASCADE"),
        nullable=False
    )
    role = Column(String(20), nullable=False)
    message = Column(Text, nullable=False)
    message_type = Column(String(50), default="text")

    created_at = Column(
        DateTime(timezone=True),
        server_default=func.now()
    )
    updated_at = Column(
        DateTime(timezone=True),
        onupdate=func.now(),
        server_default=func.now()
    )

    order = relationship("Order", back_populates="dialogs")

    def __repr__(self):
        return (
            f"<ClientDialog id={self.id} "
            f"role={self.role} "
            f"order_id={self.order_id} "
            f"created_at={self.created_at}>"
        )


class FailedOrder(Base):
    """
    Модель для таблицы 'failed_orders'.
    Хранит заказы, которые не удалось отправить в Orchestrator
    или другой внешний сервис по разным причинам (сеть, 5xx и т.д.).
    """
    __tablename__ = "failed_orders"

    id = Column(Integer, primary_key=True, index=True)
    # JSON или просто str с данными заказа
    order_data = Column(Text, nullable=False)
    reason = Column(String(255), nullable=True)
    trace_id = Column(String(50), nullable=True)

    created_at = Column(
        DateTime(timezone=True),
        server_default=func.now()
    )

    def __repr__(self):
        return f"<FailedOrder id={self.id} reason={self.reason} created_at={self.created_at}>"


class UpworkToken(Base):
    """
    Дополнительная модель для хранения токенов OAuth (Upwork) или других сервисов.
    Можно расширить полями refresh_token, scope, expires_in и т.д.
    """
    __tablename__ = "upwork_tokens"

    id = Column(Integer, primary_key=True, index=True)
    access_token = Column(String(512), nullable=False)
    refresh_token = Column(String(512), nullable=True)
    token_type = Column(String(50), nullable=True)
    # например, "jobs:read proposals:write"
    scope = Column(String(255), nullable=True)
    # время жизни токена в секундах
    expires_in = Column(Integer, nullable=True)
    created_at = Column(
        DateTime(timezone=True),
        server_default=func.now()
    )

    def __repr__(self):
        return (
            f"<UpworkToken id={self.id} "
            f"token_type={self.token_type} "
            f"created_at={self.created_at}>"
        )


# Явно указываем, какие объекты экспортируются при "from aggregator_service.models import *"
__all__ = [
    "Base",
    "OrderStatusEnum",
    "Order",
    "ClientDialog",
    "FailedOrder",
    "UpworkToken"
]
