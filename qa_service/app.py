"""
qa_service/app.py
-----------------
Боевой микросервис QA:
 - Flask + CORS + Swagger
 - Pydantic-настройки (settings.py)
 - Логирование (logging_config.py)
 - LanguageTool (для проверки текста)
 - SQLAlchemy (db.py + models.py) с Alembic
 - CRUD-операции (repository.py)

Основные эндпоинты (не изменены):
 - GET /health             : простая проверка
 - GET /info               : информация о настройках
 - POST /check-text        : основная проверка (создание записи и выполнение текст-анализа)
 - GET /qa-checks          : список проверок
 - GET /qa-checks/<id>     : детальный просмотр
 - POST /qa-checks/<id>/comments : добавить комментарий к проверке

Новая функциональность:
 - Возможность в /check-text указать "use_manager": True, чтобы задействовать 
   qa_manager.perform_qa_check (более гибкие опции: fuzzy, placeholder, ignore_rules и т.д.).
 - При use_manager=False (по умолчанию) сохраняется «старый» путь (process_text).
"""

import re
import logging
import subprocess
from typing import Dict, Any, List, Optional

from flask import Flask, request, jsonify
from flask_cors import CORS
from flasgger import Swagger, swag_from
import language_tool_python

from config.settings import get_settings
from config.logging_config import setup_logging

from db.db import SessionLocal
from db.models import QACheckStatus
from db.repository import (
    create_qa_check,
    update_qa_check_fields,
    get_qa_check_by_id,
    list_qa_checks,
    create_qa_comment,
    list_comments_for_check,
)

# -------- Новая логика: импортируем qa_manager (НЕ удаляем старую) --------
from logic.qa_manager import perform_qa_check

# ------------------------- ЛОГИРОВАНИЕ -------------------------
setup_logging()
logger = logging.getLogger("qa_service")

# ------------------------- НАСТРОЙКИ -------------------------
settings = get_settings()
PORT = settings.QA_SERVICE_PORT
DEBUG_MODE = settings.QA_SERVICE_DEBUG
LANGUAGE_CODE = settings.QA_SERVICE_LANG
BAD_WORDS = settings.bad_words_list
AUTO_CORRECT = settings.QA_SERVICE_AUTO_CORRECT
DATABASE_URL = settings.DATABASE_URL

logger.info("=== QA Service app.py START ===")
logger.info(
    "Settings -> PORT=%d, DEBUG=%s, LANG=%s, AUTO_CORRECT=%s, BAD_WORDS=%s, DB=%s",
    PORT, DEBUG_MODE, LANGUAGE_CODE, AUTO_CORRECT, BAD_WORDS, DATABASE_URL
)

# ------------------------- ALEMBIC (опционально) -------------------------


def auto_upgrade_db():
    """
    (Опционально) Запускает alembic upgrade head, чтобы обновить схему БД до последней версии.
    В продакшене обычно выполняется отдельно (до запуска приложения).
    """
    logger.info("Running 'alembic upgrade head' ...")
    try:
        result = subprocess.run(
            ["alembic", "upgrade", "head"], check=True, capture_output=True
        )
        logger.info("Alembic upgrade: %s", result.stdout.decode().strip())
    except subprocess.CalledProcessError as e:
        logger.error("Alembic failed: %s", e.stderr.decode().strip())
        raise


# ------------------------- FLASK + SWAGGER -------------------------
app = Flask(__name__)
CORS(app)
app.config["SWAGGER"] = {"title": "QA Service API", "uiversion": 3}
swagger = Swagger(app)

# ------------------------- LANGUAGE TOOL -------------------------
try:
    tool = language_tool_python.LanguageTool(LANGUAGE_CODE)
    logger.info("LanguageTool инициализирован (язык: %s).", LANGUAGE_CODE)
except Exception as e:
    logger.error("Ошибка инициализации LanguageTool: %s", e)
    tool = None

# ------------------------- DB СЕССИЯ -------------------------


def get_db_session():
    """
    Генератор, создающий и закрывающий SQLAlchemy-сессию.
    Используется: db_session = next(get_db_session())
    """
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

# ------------------------- СТАРАЯ БИЗНЕС-ЛОГИКА (НЕ УДАЛЯЕМ) -------------------------


def process_text(text: str) -> Dict[str, Any]:
    """
    Выполняет базовую логику проверки текста:
      1. Фильтрация «плохих» слов (BAD_WORDS), заменяя их на '***'.
      2. Запуск LanguageTool (если доступен)
      3. (Опционально) автокоррекция (если AUTO_CORRECT=True).
    Возвращает dict с полями:
      original_text, filtered_text, found_issues, corrected_text, warnings
    """
    filtered_text = text
    warnings = []

    for bw in BAD_WORDS:
        pattern = re.compile(rf"\b{bw}\b", re.IGNORECASE)
        filtered_text = pattern.sub("***", filtered_text)

    if tool is None:
        return {
            "original_text": text,
            "filtered_text": filtered_text,
            "found_issues": [],
            "corrected_text": None,
            "warnings": ["LanguageTool not initialized"]
        }

    matches = tool.check(filtered_text)
    found_issues = []
    for match in matches:
        found_issues.append({
            "offset": match.offset,
            "error_text": match.matchedText,
            "suggestions": match.replacements
        })

    corrected_text = None
    if AUTO_CORRECT:
        try:
            from language_tool_python.utils import correct
            corrected_text = correct(filtered_text, matches)
        except Exception as ex:
            logger.warning("Автокоррекция не удалась: %s", ex)
            warnings.append(f"Auto-correct failed: {ex}")

    return {
        "original_text": text,
        "filtered_text": filtered_text,
        "found_issues": found_issues,
        "corrected_text": corrected_text,
        "warnings": warnings
    }

# ------------------------- ЭНДПОИНТЫ -------------------------


@app.route("/health", methods=["GET"])
def health_check():
    """
    Простая проверка «живости» сервиса.
    Возвращает JSON: {"status": "OK", "service": "qa_service"}
    """
    logger.debug("Health-check called.")
    return jsonify({"status": "OK", "service": "qa_service"}), 200


@app.route("/info", methods=["GET"])
def info():
    """
    Возвращает базовую информацию о сервисе
    (название, язык, автокоррекция, кол-во «плохих» слов).
    """
    info_data = {
        "service_name": "qa_service",
        "language_code": LANGUAGE_CODE,
        "auto_correct_enabled": AUTO_CORRECT,
        "bad_words_count": len(BAD_WORDS)
    }
    logger.debug("Info called. Returning: %s", info_data)
    return jsonify(info_data), 200

# ------------------------- НОВЫЙ ПОДХОД: use_manager vs. старый -------------------------


@app.route("/check-text", methods=["POST"])
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
                    "use_manager": {"type": "boolean", "example": False},

                    # Новые опции (игнорируются, если use_manager=False)
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
            "description": "Результат проверки текста",
            "examples": {
                "application/json": {
                    "status": "ok",
                    "original_text": "Исходный",
                    "filtered_text": "Заменённый",
                    "found_issues": [],
                    "corrected_text": None,
                    "warnings": []
                }
            }
        },
        500: {
            "description": "В случае ошибки"
        }
    }
})
def check_text():
    """
    Выполняет QA-проверку текста, двумя путями:

     * use_manager=False (по умолчанию):
       - Старый подход: process_text + создание QACheck (status=PENDING -> COMPLETED)
     * use_manager=True:
       - Новый подход: qa_manager.perform_qa_check с расширенными параметрами

    Тело JSON может содержать поля:
      - text (обязательное)
      - use_manager (bool) — выбор пути
      - (прочие опции для qa_manager: auto_correct, restricted_fuzzy, language_code, etc.)
    """
    data = request.get_json() or {}
    input_text = data.get("text", "")
    use_manager = bool(data.get("use_manager", False))

    db_session = next(get_db_session())

    if not use_manager:
        # === СТАРЫЙ ПУТЬ ===
        qa_check = create_qa_check(
            db=db_session,
            original_text=input_text,
            filtered_text="",
            found_issues=[],
            corrected_text=None,
            warnings=[],
            status=QACheckStatus.PENDING
        )
        logger.debug("Created QACheck ID=%d (old path)", qa_check.id)

        try:
            result = process_text(input_text)

            update_qa_check_fields(
                db=db_session,
                check_id=qa_check.id,
                filtered_text=result["filtered_text"],
                found_issues=result["found_issues"],
                corrected_text=result["corrected_text"],
                warnings=result["warnings"],
                status=QACheckStatus.COMPLETED
            )
            logger.info(
                "Old path check-text done, QACheck ID=%d => COMPLETED", qa_check.id)
            return jsonify({"status": "ok", **result}), 200

        except Exception as e:
            logger.exception("Ошибка при /check-text (old path): %s", e)
            update_qa_check_fields(
                db=db_session,
                check_id=qa_check.id,
                warnings=(qa_check.warnings or []) + [str(e)],
                status=QACheckStatus.FAILED
            )
            return jsonify({"status": "error", "message": str(e)}), 500

        finally:
            db_session.close()

    else:
        # === НОВЫЙ ПУТЬ (qa_manager.perform_qa_check) ===
        from logic.qa_manager import perform_qa_check

        # Собираем дополнительные опции, если есть
        auto_correct = bool(data.get("auto_correct", False))
        add_log_comment = bool(data.get("add_log_comment", True))
        store_positions = bool(data.get("store_positions", False))
        store_positions_in_warnings = bool(
            data.get("store_positions_in_warnings", False))

        restricted_file_path = data.get("restricted_file_path", "")
        restricted_fuzzy = bool(data.get("restricted_fuzzy", False))
        restricted_placeholder = data.get("restricted_placeholder", "***")

        language_code = data.get("language_code", None)
        ignore_spelling_rules = data.get("ignore_spelling_rules", None)
        personal_dict = data.get("personal_dict", None)

        try:
            result = perform_qa_check(
                db=db_session,
                text=input_text,
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
            logger.exception("Ошибка при /check-text (new manager): %s", e)
            return jsonify({"status": "error", "message": str(e)}), 500

        finally:
            db_session.close()


@app.route("/qa-checks", methods=["GET"])
def get_all_qa_checks():
    """
    Возвращает список (limit=50) QACheck.
    """
    db_session = next(get_db_session())
    try:
        checks = list_qa_checks(db_session, limit=50, offset=0)
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
        logger.debug("Fetched %d QA checks.", len(result))
        return jsonify(result), 200
    except Exception as e:
        logger.exception("Ошибка при get_all_qa_checks: %s", e)
        return jsonify({"status": "error", "message": str(e)}), 500
    finally:
        db_session.close()


@app.route("/qa-checks/<int:check_id>", methods=["GET"])
def get_qa_check_details(check_id: int):
    """
    Возвращает детали QACheck (ID=check_id), включая комментарии (QAComment).
    """
    db_session = next(get_db_session())
    try:
        check_obj = get_qa_check_by_id(db_session, check_id)
        if not check_obj:
            logger.warning("QACheck not found, ID=%d", check_id)
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
        logger.debug("Detail QACheck, ID=%d => found %d comments",
                     check_id, len(comments))
        return jsonify(response), 200
    except Exception as e:
        logger.exception("Ошибка при get_qa_check_details: %s", e)
        return jsonify({"status": "error", "message": str(e)}), 500
    finally:
        db_session.close()


@app.route("/qa-checks/<int:check_id>/comments", methods=["POST"])
def add_comment_to_check(check_id: int):
    """
    Добавляет комментарий (QAComment) к QACheck (ID=check_id).
    Тело: {"comment_text": "..."}.
    """
    db_session = next(get_db_session())
    data = request.get_json() or {}
    comment_text = data.get("comment_text", "")

    try:
        check_obj = get_qa_check_by_id(db_session, check_id)
        if not check_obj:
            logger.warning(
                "QACheck not found for adding comment, ID=%d", check_id)
            return jsonify({"status": "error", "message": "QACheck not found"}), 404

        comment = create_qa_comment(db_session, check_id, comment_text)
        if not comment:
            logger.error(
                "Failed to create comment for QACheck ID=%d", check_id)
            return jsonify({"status": "error", "message": "Create comment failed"}), 500

        resp = {
            "id": comment.id,
            "comment_text": comment.comment_text,
            "created_at": str(comment.created_at),
        }
        logger.debug(
            "Created comment for QACheck ID=%d => comment_id=%d", check_id, comment.id)
        return jsonify(resp), 200

    except Exception as e:
        logger.exception("Ошибка при add_comment_to_check: %s", e)
        return jsonify({"status": "error", "message": str(e)}), 500
    finally:
        db_session.close()

# ------------------------- ГЛОБАЛЬНАЯ ОБРАБОТКА ОШИБОК -------------------------


@app.errorhandler(Exception)
def handle_exception(e):
    """
    Глобальный перехват любых непредвиденных исключений,
    чтобы сервис не падал бесшумно.
    """
    logger.exception("Непредвиденная ошибка: %s", e)
    return jsonify({"status": "error", "message": str(e)}), 500


# ------------------------- ЗАПУСК FLASK -------------------------
if __name__ == "__main__":
    logger.info(
        "Starting QA Service on port=%d, debug=%s, auto_correct=%s, lang=%s, DB=%s",
        PORT, DEBUG_MODE, AUTO_CORRECT, LANGUAGE_CODE, DATABASE_URL
    )
    # (Опционально) Автозапуск миграций
    auto_upgrade_db()

    app.run(host="0.0.0.0", port=PORT, debug=DEBUG_MODE)
