"""
tz_storage_db.py

Набор функций для работы с TЗ (Task Documents), хранящихся в таблице tz.tz_documents (JSONB).
Позволяет:
 - создавать TЗ,
 - обновлять (в том числе "глубоко", если partial_data содержит вложенные словари),
 - получать, 
 - финализировать TЗ (устанавливает status='confirmed', final_text),
 - удалять,
 - а также список (list_tz_documents) для админ/отладки.

Зависимости:
 - aggregator_service.db (SessionLocal, подключение к БД)
 - aggregator_service.models.tz_document (TZDocument)

Доп. замечания по конкурентной записи:
 - При одновременном update_tz(...) разных потоков на один order_id 
   может возникнуть гонка (последний wins).
 - Решать через транзакции, optimistic locking (версионное поле), или 
   на уровне приложения (локи).
"""

import logging
import datetime
from typing import Optional, List, Dict, Any, Union

from sqlalchemy.orm import Session
from aggregator_service.db import SessionLocal
from aggregator_service.model.tz_document import TZDocument

logger = logging.getLogger(__name__)


def create_tz(session: Session, order_id: str, initial_data: dict) -> TZDocument:
    """
    Создаёт новую запись в tz.tz_documents для конкретного order_id.

    :param session: Активная SQLAlchemy Session.
    :param order_id: Идентификатор заказа (fiverr_xxx, upwork_xxx, ...).
    :param initial_data: Словарь, который кладём в JSONB-поле 'data'.
                         Пример:
                         {
                           "status": "draft",
                           "service_type": "translation",
                           "languages": ["english","russian"],
                           "budget": 100,
                           "client_updates": []
                         }
    :return: ORM-объект TZDocument.

    :raises Exception: если order_id уже существует (unique constraint).
    """
    logger.info("Creating TЗ for order_id=%s", order_id)
    doc = TZDocument(
        order_id=order_id,
        data=initial_data
    )
    session.add(doc)
    session.commit()
    session.refresh(doc)
    logger.debug("Created TЗ id=%s order_id=%s", doc.id, order_id)
    return doc


def _deep_merge_dict(base: dict, updates: dict) -> dict:
    """
    Глубоко мёржит вложенные словари, 
    если 'updates' содержит dict, 
    рекурсивно обновляет 'base'.

    Пример:
      base = {"client_updates": [...], "nested": {"a":1, "b":2}}
      updates = {"nested": {"b": 20, "c":30}}
      => 
      {"client_updates": [...], "nested": {"a":1, "b":20, "c":30}}

    :param base: Исходный словарь (будет изменён in-place).
    :param updates: Новые данные.
    :return: base (с внесёнными изменениями).
    """
    for k, v in updates.items():
        if isinstance(v, dict) and isinstance(base.get(k), dict):
            _deep_merge_dict(base[k], v)  # рекурсия
        elif k == "client_updates":
            # Если хотим добавлять списки
            if k not in base:
                base[k] = []
            if isinstance(v, list):
                base[k].extend(v)
            else:
                logger.warning(
                    "Expected list for client_updates, got %s", type(v))
        else:
            base[k] = v
    return base


def update_tz(session: Session, order_id: str, partial_data: dict) -> TZDocument:
    """
    Загружает tz_document по order_id, 
    затем "глубоко" мёржит partial_data в JSONB 'data',
    и сохраняет результат.

    :param session: Активная SQLAlchemy Session.
    :param order_id: Идентификатор заказа.
    :param partial_data: словарь, где ключи -> поля для обновления в doc.data.
        - Если ключ = "client_updates", ожидается список, который добавится к списку "client_updates".
        - Если ключи вложенные (dict), осуществляется рекурсивный merge.
    :return: Обновлённый ORM-объект TZDocument.

    :raises ValueError: если TZDocument не найден для order_id.
    """
    logger.info("Updating TЗ for order_id=%s, updates=%s",
                order_id, partial_data)
    doc = session.query(TZDocument).filter_by(order_id=order_id).one_or_none()
    if not doc:
        raise ValueError(f"No TZDocument found for order_id={order_id}")

    base_data = doc.data or {}
    # Глубокий merge
    new_data = _deep_merge_dict(base_data, partial_data)

    doc.data = new_data
    session.commit()
    session.refresh(doc)
    logger.debug("Updated TЗ id=%s order_id=%s => data=%s",
                 doc.id, order_id, doc.data)
    return doc


def get_tz(session: Session, order_id: str) -> dict:
    """
    Возвращает doc.data (JSONB) для указанного order_id, если существует,
    иначе пустой словарь.

    :param session: Активная SQLAlchemy Session.
    :param order_id: Идентификатор заказа.
    :return: dict (JSON) с данными TЗ. 
    """
    logger.debug("Retrieving TЗ for order_id=%s", order_id)
    doc = session.query(TZDocument).filter_by(order_id=order_id).one_or_none()
    if not doc:
        logger.warning("No TЗ found for order_id=%s", order_id)
        return {}
    return doc.data


def finalize_tz(session: Session, order_id: str, final_text: str) -> TZDocument:
    """
    Устанавливает status='confirmed' и записывает итоговый текст (final_text).
    :param session: Активная SQLAlchemy Session
    :param order_id: Идентификатор заказа
    :param final_text: Окончательный текст/описание ТЗ
    :return: Обновлённый ORM-объект TZDocument

    :raises ValueError: если документ не найден.
    """
    logger.info("Finalizing TЗ for order_id=%s", order_id)
    doc = session.query(TZDocument).filter_by(order_id=order_id).one_or_none()
    if not doc:
        raise ValueError(f"No TZDocument found for order_id={order_id}")

    doc_data = doc.data or {}
    doc_data["status"] = "confirmed"
    doc_data["final_text"] = final_text
    doc.data = doc_data

    session.commit()
    session.refresh(doc)
    logger.debug("Finalized TЗ id=%s order_id=%s => data=%s",
                 doc.id, order_id, doc.data)
    return doc


def delete_tz(session: Session, order_id: str) -> bool:
    """
    Удаляет TЗ-документ из tz.tz_documents, если он есть.
    :param session: Активная SQLAlchemy Session
    :param order_id: Идентификатор заказа
    :return: True, если удалён; False, если не найден
    """
    logger.warning("Deleting TЗ for order_id=%s", order_id)
    doc = session.query(TZDocument).filter_by(order_id=order_id).one_or_none()
    if not doc:
        logger.info("No TZDocument to delete for order_id=%s", order_id)
        return False
    session.delete(doc)
    session.commit()
    logger.debug("Deleted TЗ id=%s order_id=%s", doc.id, order_id)
    return True


def list_tz_documents(session: Session, limit: int = 50, offset: int = 0) -> List[dict]:
    """
    Возвращает список TЗ (каждое = doc.data), например, для отладки/админки.
    :param session: SQLAlchemy Session
    :param limit: макс. кол-во записей
    :param offset: смещение
    :return: список dict (JSON), максимум limit штук
    """
    logger.debug("Listing TЗ documents, limit=%s offset=%s", limit, offset)
    docs = session.query(TZDocument).order_by(
        TZDocument.id).limit(limit).offset(offset).all()
    return [doc.data for doc in docs]


# ===========================
# Примеры использования (локальный тест)
# ===========================
if __name__ == "__main__":
    with SessionLocal() as session:
        order_id = "fiverr_123"
        initial_data = {
            "status": "draft",
            "service_type": "translation",
            "languages": ["english", "russian"],
            "client_updates": []
        }

        # 1) Создаём
        try:
            doc = create_tz(session, order_id, initial_data)
            print("Created doc:", doc.id, doc.order_id, doc.data)
        except Exception as e:
            print("Error creating doc:", e)

        # 2) Обновляем
        updates = {
            # пример вложенного словаря, если хотим nested merges
            "client_updates": [
                {
                    "timestamp": datetime.datetime.utcnow().isoformat() + "Z",
                    "message": "We want formal style",
                    "clarify_needed": False
                }
            ],
            "budget": 120,
            "nested_info": {
                "subfield1": "value1"
            }
        }
        try:
            updated = update_tz(session, order_id, updates)
            print("Updated doc.data:", updated.data)
        except Exception as e:
            print("Error updating doc:", e)

        # 3) Получаем
        data = get_tz(session, order_id)
        print("Loaded TЗ data:", data)

        # 4) Добавим ещё вложенный merge
        more_updates = {
            "nested_info": {
                "subfield2": "value2",
                "subnested": {
                    "key": "val"
                }
            }
        }
        update_tz(session, order_id, more_updates)

        # 5) Финализируем
        finalize_tz(session, order_id, "Окончательное ТЗ: ...")
        data2 = get_tz(session, order_id)
        print("After finalize, data:", data2)

        # (По желанию) Удаляем
        # deleted = delete_tz(session, order_id)
        # print("Deleted?", deleted)

        # Список
        all_docs = list_tz_documents(session, limit=10)
        print(f"All TЗ docs (count={len(all_docs)}):\n", all_docs)
