# aggregator_service/gigs/fiverr_gigs.py

from typing import List, Dict, Optional
import logging

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

###############################################################################
# Расширенный список поддерживаемых языков
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
# ДВА GIG'а: один для перевода (translation), другой для копирайтинга (copywriting)
###############################################################################
FIVERR_GIGS: List[Dict[str, any]] = [
    {
        "gig_id": 1111,
        "gig_type": "translation",
    },
    {
        "gig_id": 2222,
        "gig_type": "copywriting",
    }
]

###############################################################################
# Функция проверки поддерживаемости языка
###############################################################################


def is_language_supported(lang: str) -> bool:
    """
    Проверяем, содержится ли строка `lang` в списке SUPPORTED_LANGUAGES.
    """
    # Можно приводить к нижнему/верхнему регистру,
    # но здесь считаем, что нужно точное совпадение.
    return lang in SUPPORTED_LANGUAGES

###############################################################################
# Основная функция для определения, какой GIG использовать
###############################################################################


def find_fiverr_gig_for_order(
    service_type: str,
    source_lang: Optional[str] = None,
    target_lang: Optional[str] = None
) -> Optional[Dict]:
    """
    Определяет, какой gig (из FIVERR_GIGS) нужно вернуть в зависимости от:
      1) service_type: "translation" или "copywriting"
      2) source_lang, target_lang (только если service_type="translation")

    Логика:
      - Если service_type="translation", 
          * проверяем, что source_lang и target_lang есть в SUPPORTED_LANGUAGES
          * если да, возвращаем gig_type="translation" (gig_id=1111)
          * иначе None
      - Если service_type="copywriting", 
          * возвращаем gig_type="copywriting" (gig_id=2222)
      - Иначе None.

    :param service_type: строка, например "translation" / "copywriting"
    :param source_lang: "English (EN)", "Russian (RU)", ...
    :param target_lang: "English (EN)", "Russian (RU)", ...
    :return: dict (с полями "gig_id", "gig_type", "price", "delivery_days") или None
    """
    logger.info(
        f"find_fiverr_gig_for_order called with service_type={service_type}, "
        f"source_lang={source_lang}, target_lang={target_lang}"
    )

    stype_lower = service_type.lower().strip()

    # 1. Если это перевод
    if stype_lower == "translation":
        if not source_lang or not target_lang:
            logger.warning("translation requested, but missing source/target!")
            return None

        if (not is_language_supported(source_lang)) or (not is_language_supported(target_lang)):
            logger.warning(
                f"Either {source_lang} or {target_lang} not in SUPPORTED_LANGUAGES.")
            return None

        # Ищем gig_type="translation"
        for gig in FIVERR_GIGS:
            if gig["gig_type"] == "translation":
                logger.info(f"Returning translation gig: {gig}")
                return gig

        logger.info("No 'translation' gig found in FIVERR_GIGS.")
        return None

    # 2. Если это копирайт
    elif stype_lower == "copywriting":
        for gig in FIVERR_GIGS:
            if gig["gig_type"] == "copywriting":
                logger.info(f"Returning copywriting gig: {gig}")
                return gig

        logger.info("No 'copywriting' gig found in FIVERR_GIGS.")
        return None

    # 3. Никакого совпадения
    logger.warning(f"Service type={service_type} not recognized.")
    return None
