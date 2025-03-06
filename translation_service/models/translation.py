"""
translation.py — содержит Pydantic-модели (DTO) для запросов/ответов,
а также дополнительные перечисления (enum) для языков, формальностей и прочих настроек.

!!! ВНИМАНИЕ !!!
Данный код переписан под Pydantic 2.x с использованием декораторов
@field_validator и @model_validator вместо устаревших @validator и @root_validator.
Ничего из исходной структуры не удалено.
"""

import re
from typing import Optional, Dict, Any, Union
from pydantic import BaseModel, Field, field_validator, model_validator, Extra
from enum import Enum


####################################
# 1) Перечисление доступных языков (пример, расширенный)
####################################
class LanguageEnum(str, Enum):
    """
   Перечисление всех поддерживаемых языков для перевода.
   Формат: краткий код (en, es, ru...), который используется 
   при обращении к движку перевода или GPT.

   Для удобства, рядом приведены их человекочитаемые названия:
     - en = "English (EN)"
     - es = "Spanish (ES)"
     - fr = "French (FR)"
     - de = "German (DE)"
     - zh = "Chinese (ZH)"
     - ja = "Japanese (JA)"
     - ko = "Korean (KO)"
     - ar = "Arabic (AR)"
     - pt = "Portuguese (PT)"
     - ru = "Russian (RU)"
     - it = "Italian (IT)"
     - tr = "Turkish (TR)"
     - nl = "Dutch (NL)"
     - pl = "Polish (PL)"
     - uk = "Ukrainian (UK)"
     - sv = "Swedish (SV)"
     - no = "Norwegian (NO)"
     - da = "Danish (DA)"
     - fi = "Finnish (FI)"
     - hi = "Hindi (HI)"
     - id = "Indonesian (ID)"
     - ms = "Malay (MS)"
     - vi = "Vietnamese (VI)"
     - th = "Thai (TH)"
     - ro = "Romanian (RO)"
     - hu = "Hungarian (HU)"
     - cs = "Czech (CS)"
     - sk = "Slovak (SK)"
     - bg = "Bulgarian (BG)"
     - hr = "Croatian (HR)"
     - sr = "Serbian (SR)"
     - bs = "Bosnian (BS)"
     - sl = "Slovenian (SL)"
     - el = "Greek (EL)"
     - auto = "auto" (авто-определение при необходимости)
   """

    en = "en"
    es = "es"
    fr = "fr"
    de = "de"
    zh = "zh"
    ja = "ja"
    ko = "ko"
    ar = "ar"
    pt = "pt"
    ru = "ru"
    it = "it"
    tr = "tr"
    nl = "nl"
    pl = "pl"
    uk = "uk"
    sv = "sv"
    no = "no"
    da = "da"
    fi = "fi"
    hi = "hi"
    id = "id"
    ms = "ms"
    vi = "vi"
    th = "th"
    ro = "ro"
    hu = "hu"
    cs = "cs"
    sk = "sk"
    bg = "bg"
    hr = "hr"
    sr = "sr"
    bs = "bs"
    sl = "sl"
    el = "el"

# При желании оставить вариант "auto" для автодетекта:
    auto = "auto"


####################################
# 2) Перечисление формальностей (пример)
####################################
class FormalityEnum(str, Enum):
    """
    DeepL, к примеру, различает "default", "more", "less".
    GPT не требует формальных настроек, но если хотим единообразия, 
    можно хранить и для GPT.
    Google официально не поддерживает, но может игнорировать.
    """
    default = "default"
    more = "more"
    less = "less"


####################################
# 3) Модель "StylePreferences"
####################################
class StylePreferences(BaseModel):
    """
    Хранит настройки стиля: тон, домен, формальность и т.д.
    Доп. поля: glossary (dict), branding, etc. — по необходимости.

    - tone: "formal", "casual", ...
    - domain: "IT", "legal", "marketing", ...
    - formality: нужный уровень (more, less, default).
    - (опционально) glossary: если движок позволяет (например, GPT "Please use the following terms...").
    """
    tone: Optional[str] = None
    domain: Optional[str] = None
    formality: Optional[FormalityEnum] = None
    # Например, {"Frontend": "фронтенд"}
    glossary: Optional[Dict[str, str]] = None

    # Пример проверки тона
    @field_validator("tone")
    def check_tone(cls, v):
        if v and len(v) > 50:
            raise ValueError("Tone string is too long (max 50 chars).")
        return v

    class Config:
        # Если хотим позволить дополнительные поля (не объявленные)
        extra = Extra.allow


####################################
# 4) Модель "TranslationMeta"
####################################
class TranslationMeta(BaseModel):
    """
    Структурированная модель для поля 'meta' в ответе.
    Можно добавить любые поля:
      - модель движка (gpt-3.5-turbo, deepl)
      - время перевода
      - auto-detected язык
      - billing info (токены, символы)
      - ...
    """
    model: Optional[str] = Field(
        None, description="Название/версия модели (GPT, DeepL).")
    time_ms: Optional[int] = Field(
        None, description="Время перевода (миллисекунды).")
    detected_source_lang: Optional[LanguageEnum] = Field(
        None, description="Определённый движком исходный язык.")
    tokens_used: Optional[int] = Field(
        None, description="Количество израсходованных токенов (GPT).")
    # Можете добавлять что угодно дальше


####################################
# 5) Модель запроса: TranslationRequest
####################################
class TranslationRequest(BaseModel):
    """
    Pydantic-модель входного запроса на перевод.
    """
    source_text: str = Field(
        ...,
        min_length=1,
        description="Исходный текст для перевода."
    )
    source_lang: Optional[LanguageEnum] = Field(
        default=LanguageEnum.auto,
        description="Исходный язык (или 'auto' для автодетекта)."
    )
    target_lang: LanguageEnum = Field(
        ...,
        description="Целевой язык (обязателен)."
    )
    style_preferences: Optional[StylePreferences] = Field(
        default=None,
        description="Доп. настройки стиля (тон, домен, формальность, glossary)."
    )

    # Дополнительные поля, управляющие процессом перевода:
    allow_chunking: Optional[bool] = Field(
        default=False,
        description="Разрешить ли разбивать длинный текст на чанки (GPT)."
    )
    max_tokens: Optional[int] = Field(
        default=2000,
        description="Максимум токенов при вызове GPT (если движок это поддерживает)."
    )

    # Доп. валидация длины текста
    @field_validator("source_text")
    def text_length_check(cls, v):
        if len(v) > 100_000:
            raise ValueError("Слишком большой текст (более 100_000 символов).")
        return v

    # Пример root-валидации => заменяем root_validator на model_validator
    @model_validator(mode="after")
    def check_langs(cls, values):
        src = values.source_lang
        tgt = values.target_lang
        if src == tgt and src != LanguageEnum.auto:
            raise ValueError(f"source_lang и target_lang совпадают: {src}")
        return values

    class Config:
        # Запрещаем поля, не объявленные в модели (можно поменять на allow)
        extra = Extra.forbid


####################################
# 6) Модель ответа: TranslationResponse
####################################
class TranslationResponse(BaseModel):
    """
    Pydantic-модель ответа сервиса перевода.
    """
    translated_text: str = Field(
        ...,
        description="Результирующий переведённый текст."
    )
    meta: TranslationMeta = Field(
        default_factory=TranslationMeta,
        description="Служебная информация (модель, время перевода, распознанный язык, ...)."
    )

    @field_validator("translated_text")
    def check_translated_not_empty(cls, v):
        if not v.strip():
            raise ValueError("Перевод вернулся пустым.")
        return v


####################################
# 7) Пример использования
####################################
if __name__ == "__main__":
    # Пример создания модели запроса:
    req_data = {
        "source_text": "Hello world!",
        "source_lang": "en",
        "target_lang": "ru",
        "style_preferences": {
            "tone": "formal",
            "domain": "IT",
            "formality": "more",
            "glossary": {"Frontend": "фронтенд", "Backend": "бэкенд"}
        },
        "allow_chunking": True,
        "max_tokens": 1500
    }
    req = TranslationRequest(**req_data)
    print("REQUEST:", req.json(indent=2, ensure_ascii=False))

    # Пример формирования ответа:
    resp_data = {
        "translated_text": "Привет, мир!",
        "meta": {
            "model": "gpt-3.5-turbo",
            "time_ms": 1234,
            "detected_source_lang": "en",
            "tokens_used": 800
        }
    }
    resp = TranslationResponse(**resp_data)
    print("RESPONSE:", resp.json(indent=2, ensure_ascii=False))
