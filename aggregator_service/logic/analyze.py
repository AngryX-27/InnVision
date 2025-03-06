"""
analyze.py

Модуль для «анализа» входящих заказов (title/description), 
чтобы определить:
  - Тип услуги (translation / copywriting / marketing_text / ...)
  - Языковую пару (если это перевод).
  - Доп. маркеры (например, "urgent", "budget").

Пример использования:
    from aggregator_service.logic.analyze import analyze_request

    result = analyze_request("Need English to Russian translation", "Budget 50 USD, ...")
    # result -> {
    #   "service_type": "translation",
    #   "languages": ["English (EN)", "Russian (RU)"],
    #   "is_urgent": False,
    #   "budget": 50,
    #   ...
    # }
"""

import re
import logging
from typing import Dict

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

# (Если у вас уже есть aggregator_service/gigs/languages.py со списком)
# from aggregator_service.gigs.languages import SUPPORTED_LANGUAGES, is_language_supported

# Если нет отдельного файла, можно пока хранить SUPPORTED_LANGUAGES тут:
SUPPORTED_LANGUAGES = [
    "English (EN)", "Spanish (ES)", "French (FR)", "German (DE)", "Chinese (ZH)",
    "Japanese (JA)", "Korean (KO)", "Arabic (AR)", "Portuguese (PT)", "Russian (RU)",
    "Italian (IT)", "Turkish (TR)", "Dutch (NL)", "Polish (PL)", "Ukrainian (UK)",
    "Swedish (SV)", "Norwegian (NO)", "Danish (DA)", "Finnish (FI)", "Hindi (HI)",
    "Indonesian (ID)", "Malay (MS)", "Vietnamese (VI)", "Thai (TH)", "Romanian (RO)",
    "Hungarian (HU)", "Czech (CS)", "Slovak (SK)", "Bulgarian (BG)", "Croatian (HR)",
    "Serbian (SR)", "Bosnian (BS)", "Slovenian (SL)", "Greek (EL)"
]


def is_language_supported(lang: str) -> bool:
    return lang in SUPPORTED_LANGUAGES


def analyze_request(title: str, description: str) -> Dict:
    """
    Анализирует текст title+description, чтобы определить:
      - service_type: "translation" / "copywriting" / "marketing_text" / None
      - languages: список строк (["English (EN)", "Russian (RU)"]), если перевод
      - is_urgent: (bool) детект, если слово "urgent" / "ASAP" 
      - budget: (int) возможно извлечь из текста

    Возвращает dict:
      {
        "service_type": str or None,
        "languages": List[str],
        "is_urgent": bool,
        "budget": Optional[int],
        ...
      }
    """
    combined = (title + " " + description).lower()
    result = {
        "service_type": None,
        "languages": [],
        "is_urgent": False,
        "budget": None,
    }

    # 1) Проверяем, не упоминается ли "urgent", "asap"
    if any(kw in combined for kw in ["urgent", "asap"]):
        result["is_urgent"] = True

    # 2) Извлекаем budget (например, "... budget 50" / "usd 100")
    #    Очень упрощённый пример.
    #    Можно усложнить, чтобы находить "budget: 50" "budget=50" "budget is 50" "50 usd" ...
    budget_match = re.search(r"(\d+)\s*(usd|eur|usd\$|)", combined)
    if budget_match:
        try:
            result["budget"] = int(budget_match.group(1))
        except ValueError:
            pass

    # 3) Определяем service_type
    #    (простой эвристический подход)
    if any(kw in combined for kw in ["translate", "translation", "перевод"]):
        result["service_type"] = "translation"
    elif any(kw in combined for kw in ["copywriting", "copywriter", "writer"]):
        result["service_type"] = "copywriting"
    elif any(kw in combined for kw in ["marketing text", "slogan", "ad copy"]):
        result["service_type"] = "marketing_text"

    # 4) Если это "translation", пытаемся извлечь пару языков
    if result["service_type"] == "translation":
        # Простая эвристика: ищем "X to Y" / "X->Y"
        # где X,Y - должны совпадать с SUPPORTED_LANGUAGES (только упрощённо)
        # (Анализируем "English" / "Russian" / "French" ...)

        # Для каждой из SUPPORTED_LANGUAGES, упрощённо:
        # Пытаемся найти в тексте "english to russian".
        # В реальном коде лучше regex. Здесь - демонстрация идеи.
        extracted_langs = find_language_pair_in_text(combined)
        result["languages"] = extracted_langs

    logger.info(f"analyze_request => {result}")
    return result


def find_language_pair_in_text(text: str):
    """
    Сканируем SUPPORTED_LANGUAGES, пытаемся найти шаблон:
    "English to Russian" / "english -> russian" / "english -> french" ...
    Возвращаем список из 1-2 языков, что нашли.
    """
    # Пример regex: (english|french|russian)... (to|->) ... (english|french|russian)
    # Но нужно многоязычная поддержка:
    # проще: перебираем SUPPORTED_LANGUAGES, ищем, есть ли "english" + "to" + "russian"

    found_langs = []

    # Создадим вспомогательный словарь { "english": "English (EN)", ... } для матчинга
    map_lower = {}
    for lang_full in SUPPORTED_LANGUAGES:
        # Разделим, напр. "English (EN)" -> lowerkey = "english"
        # Удалим скобки: re.sub(r"\(.*?\)", "", lang_full).strip()
        # но сейчас упрощённо
        lower_lang = lang_full.split("(")[0].strip().lower()
        map_lower[lower_lang] = lang_full

    # Попробуем найти "xxx to yyy" / "xxx -> yyy"
    pattern = r"([a-zA-Z]+)\s*(?:to|->)\s*([a-zA-Z]+)"
    match = re.search(pattern, text)
    if match:
        source = match.group(1).lower()
        target = match.group(2).lower()

        # Смотрим, есть ли в map_lower
        if source in map_lower:
            found_langs.append(map_lower[source])
        if target in map_lower:
            found_langs.append(map_lower[target])

    return found_langs
