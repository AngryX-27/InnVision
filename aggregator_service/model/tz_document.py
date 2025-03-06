"""
tz_document.py

ORM-модель для хранения TЗ (Task Documents) в формате JSONB, 
расположенных в отдельной схеме 'tz', чтобы не смешивать с другими таблицами.
"""

from sqlalchemy import (
    Column,
    Integer,
    Text,
    DateTime,
    func,
    Index
)
from sqlalchemy.dialects.postgresql import JSONB
from aggregator_service.db import Base


class TZDocument(Base):
    """
    Модель tz.tz_documents для хранения ТЗ в поле JSONB:
      - order_id: строковый идентификатор заказа (fiverr_xxx, upwork_xxx)
      - data: словарь (JSONB), который содержит структуру:
          {
            "service_type": "translation"/"copywriting"/...,
            "status": "draft"/"confirmed"/...,
            "languages": ["english","russian"],  # если нужно
            "client_updates": [...],
            "final_text": "...",
            ...
          }
      - created_at, updated_at: временные метки
    """

    __tablename__ = "tz_documents"
    __table_args__ = (
        {
            "schema": "tz",          # хранится в схеме tz
            "extend_existing": True  # если уже объявлена где-то
        },
        # Пример индекса по data, если хотите через модель (необязательно):
        # Index("ix_tz_documents_data_gin", "data", postgresql_using="gin")
    )

    id = Column(Integer, primary_key=True)
    order_id = Column(Text, unique=True)
    data = Column(JSONB, nullable=False)

    created_at = Column(
        DateTime(timezone=True),
        server_default=func.now()
    )
    updated_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now()   # ORM при UPDATE автоматически ставит NOW()
    )

    def __repr__(self):
        """
        Удобное отображение при печати в логах, например: 
        <TZDocument id=12 order_id=fiverr_123>
        """
        return f"<TZDocument id={self.id} order_id={self.order_id}>"

    @property
    def status(self) -> str:
        """
        Пример свойства, если в data храните поле "status".
        Можно быстро получить/установить: doc.status = "confirmed".
        """
        return self.data.get("status", "")

    @status.setter
    def status(self, value: str):
        self.data["status"] = value
