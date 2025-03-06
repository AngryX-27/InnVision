# models/request_models.py

from typing import List, Optional, Dict, Any
from pydantic import BaseModel, Field
from enum import Enum

# =============================================================================
# Дополнительные перечисления (Enums)
# =============================================================================


class TextLength(str, Enum):
    """Уровень длины текста: короткий, средний или длинный."""
    SHORT = "short"
    MEDIUM = "medium"
    LONG = "long"


class StyleEnum(str, Enum):
    """
    Возможные стили (tones) для рекламы/блога/других текстов.
    Можно дополнять, если ваш проект требует.
    """
    ENTHUSIASTIC = "enthusiastic"
    FORMAL = "formal"
    FRIENDLY = "friendly"
    CATCHY = "catchy"
    HUMOROUS = "humorous"
    MINIMALISTIC = "minimalistic"
    TECHNICAL = "technical"
    CASUAL = "casual"


# =============================================================================
# 1. Анализ ТЗ + Генерация итогового текста (двухшаговый сценарий)
# =============================================================================

class AnalyzeClientRequirementsRequest(BaseModel):
    """
    Модель для запроса, когда Orchestrator или иной сервис отправляет
    «техзадание» (ТЗ) клиента, чтобы Role General проанализировал его и
    вернул структуру (JSON) с указанием типа, стиля, языка и др.
    """
    client_requirements: str = Field(
        ...,
        description="Полный текст ТЗ, который нужно проанализировать."
    )


class GenerateFinalTextRequest(BaseModel):
    """
    Модель для запроса, когда уже есть результат анализа (JSON-структура)
    и, возможно, дополнительный сырой текст (например, для перевода).

    analysis_result: словарь с как минимум полем 'type' (marketing, blog_post, etc.).
    raw_text: опциональный текст, если нужно что-то дополнительно учесть.
    """
    analysis_result: Dict[str, Any] = Field(
        ...,
        description="Результат анализа в виде словаря (парсинг ответа GPT). "
                    "Должен содержать хотя бы поле 'type'."
    )
    raw_text: Optional[str] = Field(
        None,
        description="Дополнительный текст, который нужно использовать (например, для перевода)."
    )
    # Дополнительные параметры генерации (опционально):
    max_tokens: Optional[int] = Field(
        None,
        description="Максимальное число токенов (по умолчанию из настроек)."
    )
    temperature: Optional[float] = Field(
        None,
        description="Креативность (0..1)."
    )
    top_p: Optional[float] = Field(
        None,
        description="top-p sampling (0..1)."
    )
    frequency_penalty: Optional[float] = Field(
        None,
        description="Штраф за повтор слов (0..2)."
    )
    presence_penalty: Optional[float] = Field(
        None,
        description="Штраф за повтор тем (0..2)."
    )


# =============================================================================
# 2. Запросы на создание конкретного контента (если вызывают напрямую)
# =============================================================================

class MarketingRequest(BaseModel):
    """
    Запрос на генерацию короткого промо-текста (продающего, рекламного).
    """
    product_or_service: str = Field(...,
                                    description="Название продукта или услуги")
    promo_goal: str = Field(
        ...,
        description="Цель рекламного текста (акция, привлечение внимания и т.д.)"
    )
    brand_voice: StyleEnum = Field(
        StyleEnum.ENTHUSIASTIC,
        description="Тон/стиль текста (enthusiastic, formal, friendly, etc.)"
    )
    max_tokens: int = Field(
        300,
        description="Максимальное число токенов в ответе (по умолчанию 300)."
    )
    # При желании можно добавить ещё поля:
    temperature: Optional[float] = Field(
        0.7,
        description="Креативность (0..1)."
    )
    top_p: Optional[float] = Field(
        1.0,
        description="Параметр top-p sampling (0..1)."
    )
    frequency_penalty: Optional[float] = Field(
        0.0,
        description="Штраф за повтор слов (0..2)."
    )
    presence_penalty: Optional[float] = Field(
        0.0,
        description="Штраф за повтор тем (0..2)."
    )


class BlogPostRequest(BaseModel):
    """
    Запрос на генерацию блог-поста.
    """
    topic: str = Field(..., description="Тема статьи (о чём писать)")
    length: TextLength = Field(
        TextLength.MEDIUM,
        description="Короткий (short), средний (medium) или длинный (long) пост"
    )
    max_tokens: int = Field(
        512,
        description="Максимальное число токенов (по умолчанию 512)."
    )
    # Дополнительные поля:
    temperature: Optional[float] = Field(0.7)
    top_p: Optional[float] = Field(1.0)
    frequency_penalty: Optional[float] = Field(0.0)
    presence_penalty: Optional[float] = Field(0.0)


class SloganRequest(BaseModel):
    """
    Запрос на создание рекламного слогана.
    """
    brand_name: str = Field(..., description="Название бренда")
    style: StyleEnum = Field(
        StyleEnum.CATCHY,
        description="Стиль слогана (catchy, formal, minimalistic, humorous, etc.)"
    )
    max_tokens: int = Field(
        50,
        description="Максимальное число токенов (по умолчанию 50)."
    )
    temperature: Optional[float] = Field(0.7)
    top_p: Optional[float] = Field(1.0)
    frequency_penalty: Optional[float] = Field(0.0)
    presence_penalty: Optional[float] = Field(0.0)


class TranslationRequest(BaseModel):
    """
    Запрос на перевод текста.
    """
    text: str = Field(...,
                      description="Исходный текст, который нужно перевести")
    target_language: str = Field(
        "English",
        description="Целевой язык перевода (English, German и т.д.)"
    )
    max_tokens: int = Field(
        256,
        description="Максимальное число токенов (по умолчанию 256)."
    )
    temperature: Optional[float] = Field(0.7)
    top_p: Optional[float] = Field(1.0)
    frequency_penalty: Optional[float] = Field(0.0)
    presence_penalty: Optional[float] = Field(0.0)


class EmailSequenceRequest(BaseModel):
    """
    Запрос на создание серии email-писем для кампании.
    """
    campaign_goal: str = Field(
        ...,
        description="Цель кампании (приветственная серия, апселл, ретаргет и т.п.)"
    )
    number_of_emails: int = Field(
        3,
        description="Количество писем в серии (по умолчанию 3)."
    )
    brand_voice: StyleEnum = Field(
        StyleEnum.FRIENDLY,
        description="Стиль текстов (friendly, formal, etc.)."
    )
    max_tokens: int = Field(
        800,
        description="Максимальное число токенов (по умолчанию 800)."
    )
    temperature: Optional[float] = Field(0.7)
    top_p: Optional[float] = Field(1.0)
    frequency_penalty: Optional[float] = Field(0.0)
    presence_penalty: Optional[float] = Field(0.0)


class SalesPageRequest(BaseModel):
    """
    Запрос на создание (или генерацию контента) для продающей лендинговой страницы.
    """
    product_name: str = Field(..., description="Название / описание продукта")
    unique_selling_points: List[str] = Field(
        ...,
        description="Список уникальных преимуществ (USP)"
    )
    target_audience: str = Field(
        "широкая аудитория",
        description="Описание ЦА"
    )
    brand_voice: StyleEnum = Field(
        StyleEnum.ENTHUSIASTIC,
        description="Тон лендинга"
    )
    max_tokens: int = Field(
        600,
        description="Максимальное число токенов (по умолчанию 600)."
    )
    temperature: Optional[float] = Field(0.7)
    top_p: Optional[float] = Field(1.0)
    frequency_penalty: Optional[float] = Field(0.0)
    presence_penalty: Optional[float] = Field(0.0)


class ProductDescriptionRequest(BaseModel):
    """
    Запрос на короткое описание продукта (для карточки товара, каталога).
    """
    product_name: str = Field(..., description="Название продукта")
    features: List[str] = Field(
        [],
        description="Список ключевых фич/характеристик"
    )
    brand_voice: StyleEnum = Field(
        StyleEnum.ENTHUSIASTIC,
        description="Стиль текста"
    )
    max_tokens: int = Field(
        300,
        description="Максимальное число токенов (по умолчанию 300)."
    )
    temperature: Optional[float] = Field(0.7)
    top_p: Optional[float] = Field(1.0)
    frequency_penalty: Optional[float] = Field(0.0)
    presence_penalty: Optional[float] = Field(0.0)


# =============================================================================
# 3. Универсальные / кастомные запросы (когда нужно что-то особенное)
# =============================================================================

class CustomPromptRequest(BaseModel):
    """
    Запрос на произвольный промпт для GPT (когда нужно что-то особенное).
    Можно указать system_role, если требуется задать особую роль
    (например, "You are an SEO marketing expert").
    """
    custom_prompt: str = Field(
        ...,
        description="Произвольная инструкция для GPT (текст от пользователя)."
    )
    system_role: str = Field(
        "You are a helpful AI assistant.",
        description="Системное сообщение (контекст), если нужно задать особую роль."
    )
    max_tokens: int = Field(
        500,
        description="Максимальное число токенов (по умолчанию 500)."
    )
    temperature: Optional[float] = Field(
        0.7,
        description="Креативность (0..1)."
    )
    top_p: Optional[float] = Field(
        1.0,
        description="top-p sampling (0..1)."
    )
    frequency_penalty: Optional[float] = Field(
        0.0,
        description="Штраф за повтор слов (0..2)."
    )
    presence_penalty: Optional[float] = Field(
        0.0,
        description="Штраф за повтор тем (0..2)."
    )
