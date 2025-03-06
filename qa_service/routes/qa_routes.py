"""
qa_service/routes/qa_routers.py
-------------------------------
Набор эндпоинтов (Blueprint) для QA-функционала:
 - GET /health
 - GET /info
 - POST /check-text
 - GET /checks
 - GET /checks/<int:check_id>
 - POST /checks/<int:check_id>/comments

Подключение в основном app.py:
    from routes.qa_routers import qa_bp
    app.register_blueprint(qa_bp, url_prefix="/qa")
"""

import logging
import re
from typing import Any, Dict

from flask import Blueprint, jsonify, request
from flasgger import swag_from
from flask_cors import CORS

# Импортируем нужные функции и модели
from db.db import SessionLocal
from db.repository import (
    create_qa_check, update_qa_check_fields, get_qa_check_by_id,
    list_qa_checks, create_qa_comment, list_comments_for_check
)
from db.models import QACheckStatus
from config.settings import get_settings
from logic.qa_manager import perform_qa_check
from logic.spell_checker import run_spell_check  # если нужно напрямую
from logic.restricted_words_checker import filter_bad_words  # если нужно напрямую

logger = logging.getLogger(__name__)

# Создаём Blueprint
qa_bp = Blueprint("qa_bp", __name__)
CORS(qa_bp)  # Если нужны CORS-заголовки для всех роутов этого блупринта

# Вспомогательная функция для получения db-сессии


def get_db_session():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

# ------------------------------------------------------------------------------
# Примеры эндпоинтов
# ------------------------------------------------------------------------------


@qa_bp.route("/health", methods=["GET"])
def health_check():
    """
    Простой health-check
    ---
    tags:
      - QA
    responses:
      200:
        description: Сервис доступен
        examples:
          application/json:
            {"status": "OK", "service": "qa_service"}
    """
    return jsonify({"status": "OK", "service": "qa_service"}), 200


@qa_bp.route("/info", methods=["GET"])
def info():
    """
    Возвращает базовую информацию о QA-сервисе (настройки).
    ---
    tags:
      - QA
    responses:
      200:
        description: Информация о сервисе
    """
    settings = get_settings()
    info_data = {
        "service_name": "qa_service",
        "language_code": settings.QA_SERVICE_LANG,
        "auto_correct_enabled": settings.QA_SERVICE_AUTO_CORRECT,
        "bad_words_count": len(settings.bad_words_list)
    }
    return jsonify(info_data), 200


@qa_bp.route("/check-text", methods=["POST"])
@swag_from({
    "tags": ["Check"],
    "parameters": [
        {
            "name": "body",
            "in": "body",
            "schema": {
                "type": "object",
                "properties": {
                    "text": {"type": "string", "example": "Это пример текста..."},
                    "auto_correct": {"type": "boolean", "example": False},
                    "add_log_comment": {"type": "boolean", "example": True},
                    "store_positions": {"type": "boolean", "example": False},
                    "store_positions_in_warnings": {"type": "boolean", "example": False},
                    "restricted_file_path": {"type": "string", "example": ""},
                    "restricted_fuzzy": {"type": "boolean", "example": False},
                    "restricted_placeholder": {"type": "string", "example": "***"},
                    "language_code": {"type": "string", "example": "ru"},
                    "ignore_spelling_rules": {
                        "type": "array",
                        "items": {"type": "string"},
                        "example": ["WHITESPACE_RULE"]
                    },
                    "personal_dict": {
                        "type": "array",
                        "items": {"type": "string"},
                        "example": ["InnVision", "QAService"]
                    }
                }
            }
        }
    ],
    "responses": {
        200: {
            "description": "Результат проверки",
            "examples": {
                "application/json": {
                    "status": "ok",
                    "original_text": "Исходный текст",
                    "filtered_text": "Очищенный текст",
                    "found_issues": [],
                    "corrected_text": None,
                    "warnings": []
                }
            }
        },
        500: {
            "description": "Ошибка при обработке"
        }
    }
})
def check_text():
    """
    Эндпоинт для запуска полной QA-проверки текста.
    Принимает JSON-поля (все опциональны, кроме text):
      - text (str)
      - auto_correct (bool)
      - add_log_comment (bool)
      - store_positions (bool)
      - store_positions_in_warnings (bool)
      - restricted_file_path (str)
      - restricted_fuzzy (bool)
      - restricted_placeholder (str)
      - language_code (str)
      - ignore_spelling_rules (List[str])
      - personal_dict (List[str])
    """
    data = request.get_json() or {}

    text = data.get("text", "")
    auto_correct = bool(data.get("auto_correct", False))
    add_log_comment = bool(data.get("add_log_comment", True))
    store_positions = bool(data.get("store_positions", False))
    store_positions_in_warnings = bool(
        data.get("store_positions_in_warnings", False))

    restricted_file_path = data.get("restricted_file_path", "")
    restricted_fuzzy = bool(data.get("restricted_fuzzy", False))
    restricted_placeholder = data.get("restricted_placeholder", "***")

    language_code = data.get("language_code", None)  # e.g. "ru", "en-US"
    ignore_spelling_rules = data.get("ignore_spelling_rules", None)
    personal_dict = data.get("personal_dict", None)

    db_session = next(get_db_session())
    try:
        result = perform_qa_check(
            db=db_session,
            text=text,
            auto_correct=auto_correct,
            add_log_comment=add_log_comment,
            store_positions=store_positions,
            store_positions_in_warnings=store_positions_in_warnings,
            restricted_file_path=restricted_file_path,
            restricted_fuzzy=restricted_fuzzy,
            restricted_placeholder=restricted_placeholder,
            language_code=language_code,
            ignore_spelling_rules=ignore_spelling_rules,
            personal_dict=personal_dict
        )
        status_code = 200 if result["status"] == "ok" else 500
        return jsonify(result), status_code

    except Exception as e:
        logger.exception("Ошибка при /check-text: %s", e)
        return jsonify({"status": "error", "message": str(e)}), 500
    finally:
        db_session.close()


@qa_bp.route("/checks", methods=["GET"])
def get_all_qa_checks():
    """
    Возвращает список (limit=50) последних QACheck.
    ---
    tags:
      - Check
    responses:
      200:
        description: Список проверок
    """
    limit = int(request.args.get("limit", 50))
    offset = int(request.args.get("offset", 0))

    db_session = next(get_db_session())
    try:
        checks = list_qa_checks(db_session, limit=limit, offset=offset)
        result = []
        for ch in checks:
            result.append({
                "id": ch.id,
                "original_text": ch.original_text,
                "filtered_text": ch.filtered_text,
                "found_issues": ch.found_issues,
                "corrected_text": ch.corrected_text,
                "warnings": ch.warnings,
                "status": ch.status.value,
                "created_at": str(ch.created_at),
                "updated_at": str(ch.updated_at),
            })
        return jsonify(result), 200
    except Exception as e:
        logger.exception("Ошибка при get_all_qa_checks: %s", e)
        return jsonify({"status": "error", "message": str(e)}), 500
    finally:
        db_session.close()


@qa_bp.route("/checks/<int:check_id>", methods=["GET"])
def get_qa_check_details(check_id: int):
    """
    Возвращает детальную информацию о QACheck, включая комментарии (QAComment).
    ---
    tags:
      - Check
    parameters:
      - name: check_id
        in: path
        type: integer
        required: True
    responses:
      200:
        description: Детали проверки
      404:
        description: Не найдено
    """
    db_session = next(get_db_session())
    try:
        check_obj = get_qa_check_by_id(db_session, check_id)
        if not check_obj:
            return jsonify({"status": "error", "message": "Not found"}), 404

        comments = list_comments_for_check(db_session, check_id)
        response = {
            "id": check_obj.id,
            "original_text": check_obj.original_text,
            "filtered_text": check_obj.filtered_text,
            "found_issues": check_obj.found_issues,
            "corrected_text": check_obj.corrected_text,
            "warnings": check_obj.warnings,
            "status": check_obj.status.value,
            "created_at": str(check_obj.created_at),
            "updated_at": str(check_obj.updated_at),
            "comments": [
                {
                    "id": c.id,
                    "comment_text": c.comment_text,
                    "created_at": str(c.created_at)
                } for c in comments
            ]
        }
        return jsonify(response), 200
    except Exception as e:
        logger.exception("Ошибка при get_qa_check_details: %s", e)
        return jsonify({"status": "error", "message": str(e)}), 500
    finally:
        db_session.close()


@qa_bp.route("/checks/<int:check_id>/comments", methods=["POST"])
def add_comment_to_check(check_id: int):
    """
    Добавляет комментарий (QAComment) к указанной проверке.
    Тело запроса: {"comment_text": "..."}.
    ---
    tags:
      - Comments
    parameters:
      - name: check_id
        in: path
        type: integer
        required: True
      - name: body
        in: body
        schema:
          type: object
          properties:
            comment_text:
              type: string
              example: "Здесь мои замечания"
    responses:
      200:
        description: Комментарий создан
      404:
        description: QACheck не найден
      500:
        description: Ошибка при создании
    """
    data = request.get_json() or {}
    comment_text = data.get("comment_text", "")

    db_session = next(get_db_session())
    try:
        check_obj = get_qa_check_by_id(db_session, check_id)
        if not check_obj:
            return jsonify({"status": "error", "message": "QACheck not found"}), 404

        comment = create_qa_comment(db_session, check_id, comment_text)
        if not comment:
            return jsonify({"status": "error", "message": "Create comment failed"}), 500

        resp = {
            "id": comment.id,
            "comment_text": comment.comment_text,
            "created_at": str(comment.created_at)
        }
        return jsonify(resp), 200
    except Exception as e:
        logger.exception("Ошибка при add_comment_to_check: %s", e)
        return jsonify({"status": "error", "message": str(e)}), 500
    finally:
        db_session.close()
