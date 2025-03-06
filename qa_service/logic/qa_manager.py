"""
qa_service/logic/qa_manager.py
------------------------------
Главный «менеджер» для QA-проверки текста.

КЛЮЧЕВАЯ ЛОГИКА:
  1. Создаёт запись QACheck (status=PENDING).
  2. Фильтрует «плохие» слова через restricted_words_checker (с учётом опций: file_path, fuzzy, placeholder).
     (Опционально) может отслеживать позиции, где слова были заменены (track_positions).
  3. Запускает spell_checker.run_spell_check (LanguageTool) с учётом:
     - auto_correct
     - language_code
     - ignore_spelling_rules
     - personal_dict (словарь разрешённых слов)
  4. Обновляет запись в БД (COMPLETED или FAILED).
  5. (Опционально) добавляет QAComment, если add_log_comment=True.

ПАРАМЕТРЫ, КОТОРЫЕ МОЖНО ПЕРЕДАВАТЬ:

  :param db:             SQLAlchemy-сессия
  :param text:           Исходный текст, который нужно проверить
  :param auto_correct:   Включает автокоррекцию (True/False)
  :param add_log_comment:Нужно ли создать QAComment с итогом/ошибкой
  :param store_positions:Если True, будем вызывать check_and_replace_bad_words_positions 
                         и получать «positions» замен; добавим их в возвращаемый словарь
  :param store_positions_in_warnings: Если True, добавляем «positions» как одну из «warnings», 
                         чтобы можно было видеть заменённые сегменты прямо в QACheck.warnings
  :param restricted_file_path: Путь к файлу со «плохими» словами (дополнительно к ENV)
  :param restricted_fuzzy:     Если True, ищем «плохие» слова без границ (\b)
  :param restricted_placeholder: На что заменяем «плохие» слова (по умолчанию '***')

  :param language_code:        Код языка для LanguageTool (e.g. "ru", "en-US")
  :param ignore_spelling_rules:Список ID правил, отключаемых в LT (e.g. ["WHITESPACE_RULE"])
  :param personal_dict:        Список слов, которые не считать ошибкой (e.g. ["InnVision"])

ВОЗВРАЩАЕТ dict:
  {
    "check_id": int,
    "status": "ok" | "error",
    "original_text": str,
    "filtered_text": str,
    "found_issues": List[dict],
    "corrected_text": Optional[str],
    "warnings": List[str],
    "positions": Optional[List[Tuple[int, int, str]]],  # если store_positions=True
    "message": Optional[str]  # при ошибке
  }

"""

import logging
from typing import Dict, Any, Optional, List, Tuple

from sqlalchemy.orm import Session

# Базовые CRUD-функции
from db.repository import (
    create_qa_check,
    update_qa_check_fields,
    create_qa_comment,
)

from db.models import QACheckStatus

# Модули фильтрации «плохих» слов и орфографии
from logic.restricted_words_checker import (
    filter_bad_words,
    check_and_replace_bad_words_positions
)
from logic.spell_checker import run_spell_check

logger = logging.getLogger(__name__)


def perform_qa_check(
    db: Session,
    text: str,
    auto_correct: bool = False,
    add_log_comment: bool = True,
    store_positions: bool = False,
    store_positions_in_warnings: bool = False,

    # ПАРАМЕТРЫ ДЛЯ restricted_words_checker
    restricted_file_path: str = "",
    restricted_fuzzy: bool = False,
    restricted_placeholder: str = "***",

    # ПАРАМЕТРЫ ДЛЯ spell_checker
    language_code: Optional[str] = None,
    ignore_spelling_rules: Optional[List[str]] = None,
    personal_dict: Optional[List[str]] = None
) -> Dict[str, Any]:
    """
    Выполняет полный цикл QA-проверки текста.

    1) Создаёт запись QACheck (status=PENDING).
    2) Фильтрует «плохие» слова:
       - Если store_positions=True, используем check_and_replace_bad_words_positions,
         тогда можем получить список позиций замен.
       - Иначе filter_bad_words (только замена, без позиций).
    3) Запускает spell_checker (run_spell_check) c опциями:
       auto_correct, language_code, ignore_spelling_rules, personal_dict.
    4) Обновляет запись (COMPLETED) или при Exception -> (FAILED),
       дополняет QACheck.warnings, если есть замечания/ошибки.
    5) (Опционально) Добавляет QAComment.
    6) Возвращает итоговый словарь:
       {
         "check_id": int,
         "status": "ok" | "error",
         "original_text": str,
         "filtered_text": str,
         "found_issues": List[dict],
         "corrected_text": Optional[str],
         "warnings": List[str],
         "positions": Optional[List[Tuple[int, int, str]]], # если store_positions=True
         "message": Optional[str] # при ошибке
       }

    :param db: SQLAlchemy-сессия
    :param text: Исходный текст
    :param auto_correct: включать ли автокоррекцию (True/False)
    :param add_log_comment: создавать ли QAComment с коротким описанием (True/False)
    :param store_positions: если True, фильтруем «плохие» слова c отслеживанием позиций замен
    :param store_positions_in_warnings: если True, добавляем positions в warnings
    :param restricted_file_path: путь к файлу для bad words (дополнительно к ENV)
    :param restricted_fuzzy: искать ли подстроки (fuzzy=True) или целые слова (\b)
    :param restricted_placeholder: замена для «плохих» слов, по умолчанию '***'
    :param language_code: код языка для LT, e.g. "ru", "en-US"
    :param ignore_spelling_rules: список ID правил, которые нужно отключить
    :param personal_dict: список слов, считающихся «нормальными» (не ошибка)

    :return: итоговый dict
    """

    # 1) Создаём запись QACheck (PENDING)
    qa_check = create_qa_check(
        db=db,
        original_text=text,
        filtered_text="",
        found_issues=[],
        corrected_text=None,
        warnings=[],
        status=QACheckStatus.PENDING
    )

    try:
        # 2) Фильтрация «плохих» слов
        positions = None
        if store_positions:
            # Получаем сразу и «очищенный» текст, и positions
            filter_result = check_and_replace_bad_words_positions(
                text=text,
                file_path=restricted_file_path,
                placeholder=restricted_placeholder,
                fuzzy=restricted_fuzzy
            )
            filtered_text = filter_result["filtered_text"]
            positions = filter_result["positions"]
        else:
            # Старый путь: просто заменяем
            filtered_text = filter_bad_words(
                text=text,
                file_path=restricted_file_path,
                placeholder=restricted_placeholder,
                fuzzy=restricted_fuzzy
            )

        # 3) Запуск проверки (орфография/грамматика)
        check_result = run_spell_check(
            text=filtered_text,
            auto_correct=auto_correct,
            language_code=language_code,
            ignore_rules=ignore_spelling_rules,
            personal_dict=personal_dict
        )

        found_issues = check_result.get("found_issues", [])
        warnings = check_result.get("warnings", [])
        corrected_text = check_result.get("corrected_text")

        # Если нужно «вшить» positions в warnings
        if store_positions and store_positions_in_warnings and positions:
            # Сериализуем positions как строку
            positions_str = f"Positions replaced: {positions}"
            warnings.append(positions_str)

        # 4) Обновляем запись (COMPLETED)
        update_qa_check_fields(
            db=db,
            check_id=qa_check.id,
            filtered_text=filtered_text,
            found_issues=found_issues,
            corrected_text=corrected_text,
            warnings=warnings,
            status=QACheckStatus.COMPLETED
        )

        # (Опционально) QAComment
        if add_log_comment:
            comment_text = (
                f"QA check completed:\n"
                f"Original(50 chars): {text[:50]}...\n"
                f"Filtered(50 chars): {filtered_text[:50]}...\n"
                f"Issues: {len(found_issues)}, Warnings: {len(warnings)}"
            )
            if store_positions and positions:
                comment_text += f"\nPositions replaced: {positions}"
            create_qa_comment(db, qa_check.id, comment_text)

        # Формируем результат (status="ok")
        result_dict = {
            "check_id": qa_check.id,
            "status": "ok",
            "original_text": text,
            "filtered_text": filtered_text,
            "found_issues": found_issues,
            "corrected_text": corrected_text,
            "warnings": warnings
        }
        if store_positions:
            result_dict["positions"] = positions

        return result_dict

    except Exception as e:
        logger.exception("Ошибка при perform_qa_check: %s", e)
        # При ошибке => FAILED
        update_qa_check_fields(
            db=db,
            check_id=qa_check.id,
            warnings=(qa_check.warnings or []) + [str(e)],
            status=QACheckStatus.FAILED
        )

        if add_log_comment:
            create_qa_comment(db, qa_check.id, f"Ошибка QA: {e}")

        return {
            "check_id": qa_check.id,
            "status": "error",
            "message": str(e),
            "original_text": text,
            "filtered_text": "",
            "found_issues": [],
            "corrected_text": None,
            "warnings": [str(e)]
        }
