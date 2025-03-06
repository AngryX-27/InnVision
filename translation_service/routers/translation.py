"""
routers/translation.py

Описание:
Этот модуль содержит FastAPI-роуты, связанные с операциями перевода.
Он:
1) Принимает POST /translate (JSON с текстом, исходным языком и т.д.).
2) Вызывает бизнес-логику (perform_translation) из translator_interface.
3) Возвращает ответ в формате TranslationResponse.
4) Содержит health-check GET /health.
"""

import logging
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

# Импорт Pydantic-моделей (запрос/ответ) из models/translation.py
from translation_service.models.translation import TranslationRequest, TranslationResponse

# Бизнес-логика перевода (функция, которая координирует GPT/DeepL/Google + постобработку)
from translation_service.services.translator_interface import perform_translation

# Зависимость для получения SQLAlchemy-сессии из вашего модуля db (пример: db/database.py)
# Предположим, у вас есть функция get_db() → Session
from aggregator_service.aggregator_db.session import get_db

# Дополнительно, если нужно подтягивать настройки
from translation_service.config import settings

router = APIRouter()
logger = logging.getLogger(__name__)


@router.post("/translate", response_model=TranslationResponse, summary="Перевод текста")
async def translate_text(
    request: TranslationRequest,
    db: Session = Depends(get_db)
):
    """
    Эндпоинт для перевода текста.

    Принимает:
    - JSON (TranslationRequest): source_text, source_lang, target_lang, style_preferences

    Возвращает:
    - TranslationResponse: translated_text, meta (доп. информация)

    Пример запроса:
    POST /translate
    {
      "source_text": "Hello world!",
      "source_lang": "en",
      "target_lang": "ru",
      "style_preferences": {
        "tone": "formal",
        "domain": "IT",
        "formality": "more"
      }
    }

    Пример ответа:
    {
      "translated_text": "Привет, мир!",
      "meta": {
        "source_lang": "en",
        "target_lang": "ru",
        "model": "gpt-3.5-turbo",
        "time_ms": 1234
      }
    }
    """
    try:
        # Логируем начало запроса
        logger.info(
            f"Получен запрос на перевод. Источник: {request.source_lang}, Цель: {request.target_lang}")

        # Вызываем бизнес-логику перевода (GPT/DeepL/Google + постобработка)
        translated_text = await perform_translation(
            db=db,
            text=request.source_text,
            source_lang=request.source_lang.value if hasattr(
                request.source_lang, "value") else request.source_lang,
            target_lang=request.target_lang.value if hasattr(
                request.target_lang, "value") else request.target_lang,
            style=request.style_preferences
        )

        # Формируем ответ
        response_data = TranslationResponse(
            translated_text=translated_text,
            meta={
                "source_lang": request.source_lang,
                "target_lang": request.target_lang,
                "style_preferences": request.style_preferences or {}
            }
        )
        logger.info("Перевод успешно выполнен.")
        return response_data

    except HTTPException as http_exc:
        # Если внутри perform_translation выбросили HTTPException
        logger.warning(f"HTTPException при переводе: {http_exc.detail}")
        raise http_exc

    except Exception as e:
        # Непредвиденная ошибка
        logger.error(f"Ошибка при переводе: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=500, detail="Internal server error during translation")


@router.get("/health", summary="Проверка работоспособности сервиса")
def health_check():
    """
    Эндпоинт для проверки здоровья (health-check).
    Возвращает простой статус. Можно дополнить проверкой соединения с БД, ключами API и т.д.

    Пример ответа:
    {
      "status": "ok"
    }
    """
    # При желании, можно проверить, доступна ли БД:
    # try:
    #     db = next(get_db())
    #     db.execute("SELECT 1;")
    # except:
    #     return {"status": "db_error"}
    return {"status": "ok"}
