"""
languages.py

Хранит список всех языков, поддерживаемых InnVision, и функции
для проверки или нормализации языковых кодов.

Используется в aggregator_service/gigs/ для определения,
поддерживается ли данный язык сервисом. 
"""

import logging
from typing import List

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

###############################################################################
# 1. Полный список поддерживаемых языков
###############################################################################
SUPPORTED_LANGUAGES: List[str] = [
    "English (EN)",
    "Spanish (ES)",
    "French (FR)",
    "German (DE)",
    "Chinese (ZH)",
    "Japanese (JA)",
    "Korean (KO)",
    "Arabic (AR)",
    "Portuguese (PT)",
    "Russian (RU)",
    "Italian (IT)",
    "Turkish (TR)",
    "Dutch (NL)",
    "Polish (PL)",
    "Ukrainian (UK)",
    "Swedish (SV)",
    "Norwegian (NO)",
    "Danish (DA)",
    "Finnish (FI)",
    "Hindi (HI)",
    "Indonesian (ID)",
    "Malay (MS)",
    "Vietnamese (VI)",
    "Thai (TH)",
    "Romanian (RO)",
    "Hungarian (HU)",
    "Czech (CS)",
    "Slovak (SK)",
    "Bulgarian (BG)",
    "Croatian (HR)",
    "Serbian (SR)",
    "Bosnian (BS)",
    "Slovenian (SL)",
    "Greek (EL)"
]

###############################################################################
# 2. Функция проверки, поддерживаем ли мы указанный язык
###############################################################################


def is_language_supported(lang: str) -> bool:
    """
    Проверяем, содержится ли строка lang в списке SUPPORTED_LANGUAGES.

    :param lang: Название языка, например "English (EN)", "Russian (RU)" и т.д.
    :return: True, если этот язык есть в SUPPORTED_LANGUAGES, иначе False.
    """
    # Можно привести lang к какому-то общему формату (lower / upper),
    # но если в SUPPORTED_LANGUAGES записаны в конкретном виде,
    # то оставляем точное сравнение:
    result = lang in SUPPORTED_LANGUAGES
    if not result:
        logger.info(f"Язык '{lang}' не поддерживается.")
    return result

###############################################################################
# 3. (Опционально) Функция normalize_language (если вы хотите
#    приводить входящие значения "English", "english (EN)", и т.п. к единообразию).
###############################################################################


def normalize_language(lang: str) -> str:
    """
    Можно использовать, если приходят варианты вроде "english" или "English(EN)".
    Здесь вы решаете, как именно приводить.
    В базовой реализации пока просто strip().

    :param lang: строка, описывающая язык
    :return: та же строка, но очищенная от лишних пробелов
    """
    return lang.strip()
