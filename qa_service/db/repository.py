"""
qa_service/db/repository.py
---------------------------
Набор репозиторных (CRUD) функций для работы с моделями QACheck, QAComment (и др., если нужно).

Основные методы:
 - create_qa_check, get_qa_check_by_id, update_qa_check, delete_qa_check...
 - create_qa_comment, list_comments_for_check, delete_qa_comment...
 - list_qa_checks (с фильтрами, пагинацией)
 - Примеры расширенных сценариев: find_by_status, mass_delete_old_checks...

Все операции принимают SQLAlchemy Session (db: Session), 
которую можно получать через get_session() или session_scope() из db.py.

Пример использования:
    from db.db import get_session
    from db.repository import create_qa_check

    with session_scope() as db:
        check = create_qa_check(db, original_text="Hello...", filtered_text="...", ...)
        ...
"""

import logging
from typing import List, Optional, Dict, Any, Union
from datetime import datetime, timedelta

from sqlalchemy.orm import Session
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy import func, and_

from db.models import QACheck, QACheckStatus, QAComment

logger = logging.getLogger(__name__)

# ------------------------------------------------------------------------------
# QACheck CRUD
# ------------------------------------------------------------------------------


def create_qa_check(
    db: Session,
    original_text: str,
    filtered_text: str,
    found_issues: Optional[List[Dict[str, Any]]] = None,
    corrected_text: Optional[str] = None,
    warnings: Optional[List[str]] = None,
    status: QACheckStatus = QACheckStatus.PENDING
) -> QACheck:
    """
    Создаёт новую запись QACheck в БД.

    :param db: Session
    :param original_text: исходный текст
    :param filtered_text: текст после фильтрации
    :param found_issues: список ошибок (JSON-список [{offset, error_text, suggestions}...])
    :param corrected_text: автокорректированный текст
    :param warnings: список предупреждений (JSON-список строк)
    :param status: QACheckStatus (по умолчанию pending)

    :return: созданный объект QACheck
    """
    if found_issues is None:
        found_issues = []
    if warnings is None:
        warnings = []

    try:
        qa_check = QACheck(
            original_text=original_text,
            filtered_text=filtered_text,
            found_issues=found_issues,
            corrected_text=corrected_text,
            warnings=warnings,
            status=status
        )
        db.add(qa_check)
        db.commit()
        db.refresh(qa_check)
        logger.debug("Created QACheck id=%s status=%s",
                     qa_check.id, qa_check.status)
        return qa_check
    except SQLAlchemyError as e:
        db.rollback()
        logger.exception("Error creating QACheck: %s", e)
        raise


def get_qa_check_by_id(db: Session, check_id: int) -> Optional[QACheck]:
    """
    Возвращает QACheck по заданному id, либо None, если не найден.
    """
    try:
        return db.query(QACheck).filter(QACheck.id == check_id).one_or_none()
    except SQLAlchemyError as e:
        logger.exception("Error fetching QACheck by id=%s: %s", check_id, e)
        return None


def update_qa_check_fields(
    db: Session,
    check_id: int,
    filtered_text: Optional[str] = None,
    found_issues: Optional[List[Dict[str, Any]]] = None,
    corrected_text: Optional[str] = None,
    warnings: Optional[List[str]] = None,
    status: Optional[QACheckStatus] = None
) -> Optional[QACheck]:
    """
    Обновляет определённые поля QACheck (выборочно).
    Возвращает обновлённый объект или None, если не найден.

    Пример:
      update_qa_check_fields(db, check_id=123, status=QACheckStatus.COMPLETED)
    """
    try:
        qa_check = db.query(QACheck).filter(
            QACheck.id == check_id).one_or_none()
        if not qa_check:
            return None

        if filtered_text is not None:
            qa_check.filtered_text = filtered_text
        if found_issues is not None:
            qa_check.found_issues = found_issues
        if corrected_text is not None:
            qa_check.corrected_text = corrected_text
        if warnings is not None:
            qa_check.warnings = warnings
        if status is not None:
            qa_check.status = status

        db.commit()
        db.refresh(qa_check)
        logger.debug("Partially updated QACheck id=%s status=%s",
                     check_id, qa_check.status)
        return qa_check
    except SQLAlchemyError as e:
        db.rollback()
        logger.exception("Error updating QACheck fields: %s", e)
        return None


def delete_qa_check(db: Session, check_id: int) -> bool:
    """
    Удаляет QACheck по ID. Возвращает True, если запись была успешно удалена, False, если не найдена или ошибка.
    """
    try:
        qa_check = db.query(QACheck).filter(
            QACheck.id == check_id).one_or_none()
        if not qa_check:
            return False
        db.delete(qa_check)
        db.commit()
        logger.debug("Deleted QACheck id=%s", check_id)
        return True
    except SQLAlchemyError as e:
        db.rollback()
        logger.exception("Error deleting QACheck: %s", e)
        return False


def list_qa_checks(
    db: Session,
    limit: int = 50,
    offset: int = 0,
    status: Optional[QACheckStatus] = None,
    order_desc: bool = True
) -> List[QACheck]:
    """
    Возвращает список QACheck с учётом пагинации limit/offset.
    Можно отфильтровать по статусу. По умолчанию сортируем по id desc.
    """
    try:
        query = db.query(QACheck)
        if status:
            query = query.filter(QACheck.status == status)
        if order_desc:
            query = query.order_by(QACheck.id.desc())
        else:
            query = query.order_by(QACheck.id.asc())

        return query.limit(limit).offset(offset).all()
    except SQLAlchemyError as e:
        logger.exception("Error listing QACheck: %s", e)
        return []


def find_by_status(
    db: Session,
    status: QACheckStatus,
    limit: int = 50
) -> List[QACheck]:
    """
    Возвращает все QACheck с указанным статусом (ограничение limit).
    """
    try:
        return db.query(QACheck) \
                 .filter(QACheck.status == status) \
                 .order_by(QACheck.id.desc()) \
                 .limit(limit).all()
    except SQLAlchemyError as e:
        logger.exception("Error find_by_status: %s", e)
        return []


def mass_delete_old_checks(
    db: Session,
    older_than_days: int = 30
) -> int:
    """
    Пример массового удаления: удаляет QACheck, у которых updated_at < (сейчас - older_than_days).
    Возвращает количество удалённых записей.
    """
    try:
        cutoff = datetime.utcnow() - timedelta(days=older_than_days)
        result = db.query(QACheck).filter(QACheck.updated_at <
                                          cutoff).delete(synchronize_session=False)
        db.commit()
        logger.info(
            "mass_delete_old_checks(): deleted %d old checks older than %d days", result, older_than_days)
        return result
    except SQLAlchemyError as e:
        db.rollback()
        logger.exception("Error mass_delete_old_checks: %s", e)
        return 0

# ------------------------------------------------------------------------------
# QAComment CRUD
# ------------------------------------------------------------------------------


def create_qa_comment(db: Session, qa_check_id: int, comment_text: str) -> Optional[QAComment]:
    """
    Создаёт новый комментарий (QAComment) для QACheck (id=qa_check_id).
    Возвращает созданный объект или None при ошибке.
    """
    try:
        comment = QAComment(
            qa_check_id=qa_check_id,
            comment_text=comment_text
        )
        db.add(comment)
        db.commit()
        db.refresh(comment)
        logger.debug("Created QAComment id=%s for qa_check_id=%s",
                     comment.id, qa_check_id)
        return comment
    except SQLAlchemyError as e:
        db.rollback()
        logger.exception("Error creating QAComment: %s", e)
        return None


def list_comments_for_check(db: Session, qa_check_id: int) -> List[QAComment]:
    """
    Возвращает все комментарии (QAComment), связанные с данным QACheck (qa_check_id).
    """
    try:
        return db.query(QAComment) \
                 .filter(QAComment.qa_check_id == qa_check_id) \
                 .order_by(QAComment.id.desc()) \
                 .all()
    except SQLAlchemyError as e:
        logger.exception(
            "Error fetching QAComments for check_id=%s: %s", qa_check_id, e)
        return []


def delete_qa_comment(db: Session, comment_id: int) -> bool:
    """
    Удаляет комментарий (QAComment) по его id. 
    Возвращает True, если успешно удалён, False — если не найден или ошибка.
    """
    try:
        comment = db.query(QAComment).filter(
            QAComment.id == comment_id).one_or_none()
        if not comment:
            return False
        db.delete(comment)
        db.commit()
        logger.debug("Deleted QAComment id=%s", comment_id)
        return True
    except SQLAlchemyError as e:
        db.rollback()
        logger.exception("Error deleting QAComment: %s", e)
        return False


# ------------------------------------------------------------------------------
# Дополнительные репозиториные методы (примеры)
# ------------------------------------------------------------------------------
def update_comment_text(
    db: Session,
    comment_id: int,
    new_text: str
) -> Optional[QAComment]:
    """
    Обновляет текст комментария (QAComment), возвращает обновлённый объект или None.
    """
    try:
        c = db.query(QAComment).filter(
            QAComment.id == comment_id).one_or_none()
        if not c:
            return None
        c.comment_text = new_text
        db.commit()
        db.refresh(c)
        logger.debug("Updated QAComment id=%s with new_text length=%d",
                     comment_id, len(new_text))
        return c
    except SQLAlchemyError as e:
        db.rollback()
        logger.exception("Error update_comment_text: %s", e)
        return None
