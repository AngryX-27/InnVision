"""
translator_interface.py — «Высокоуровневый» модуль, координирующий перевод:
1) Сначала Deepl перевод (если поддерживает комбинацию). Если не получилось — Google.
2) Потом GPT (gpt-4) делает "sense-check" / "improve style" уже переведённого текста.
3) Опциональное разбиение текста по абзацам (allow_chunking=True).
4) Постобработка (глоссарий, forbidden words).
5) Сохранение результата в кэш (TranslationMemory).
"""

import logging
import time
from typing import Optional, Dict, List

from sqlalchemy.orm import Session

# ORM-модель для кэша
from translation_service.db.models import TranslationMemory

# Движки перевода
from translation_service.services.translator_gpt import translate_with_gpt
from translation_service.services.translator_deepl import translate_with_deepl
from translation_service.services.translator_google import translate_with_google

# Расширенная постобработка
from translation_service.services.postprocessing import postprocess_text

# Конфиг (содержит ключи/настройки)
from translation_service.config import settings

logger = logging.getLogger(__name__)

########################################
# Работа с TranslationMemory (кэш)
########################################


def get_translation_from_memory(db: Session, text: str, src: str, tgt: str) -> Optional[str]:
    """
    Проверяем, есть ли готовый перевод (src→tgt, text) в БД (TranslationMemory).
    Возвращаем перевод или None.
    """
    rec = (
        db.query(TranslationMemory)
        .filter_by(source_text=text, source_lang=src, target_lang=tgt)
        .first()
    )
    if rec:
        logger.info("Найден перевод в TranslationMemory (кэш).")
        return rec.translated_text
    return None


def save_translation_to_memory(db: Session, text: str, translated: str, src: str, tgt: str) -> None:
    """
    Сохраняем перевод (text->translated) в кэш, 
    чтобы при повторном обращении не вызывать движки заново.
    """
    new_item = TranslationMemory(
        source_text=text,
        translated_text=translated,
        source_lang=src,
        target_lang=tgt
    )
    db.add(new_item)
    db.commit()
    logger.debug("Перевод добавлен в TranslationMemory.")


########################################
# Основная логика перевода
########################################

async def perform_translation(
    db: Session,
    text: str,
    source_lang: Optional[str],
    target_lang: str,
    style: Optional[Dict] = None,
    allow_chunking: bool = False,
    chunk_size: int = 3000,
    domain: Optional[str] = None,
    subdomain: Optional[str] = None,
    postproc_smart_mask: bool = False,
    postproc_throw_on_forbidden: bool = False
) -> str:
    """
    Выполняет перевод текста (src→tgt) по новой логике:
      1) Сначала Deepl (если поддерживает этот язык, есть ключи).
      2) Если не получилось — Google.
      3) Далее GPT-4 ("sense-check") улучшает перевод (переформулирует и правит смысл).
      4) Постобработка (глоссарий, forbidden words).
      5) Сохранение результата в кэш.

    Параметры:
      - db: SQLAlchemy сессия
      - text: исходный текст
      - source_lang: напр. "en", "ru" (или None => 'auto')
      - target_lang: напр. "en", "ru"
      - style: dict (tone, domain, formality...) для движков
      - allow_chunking: True => разбивка по абзацам
      - chunk_size: макс размер части (3000 символов)
      - domain, subdomain: постобработка, глоссарий
      - postproc_smart_mask: True => маскировать forbidden words
      - postproc_throw_on_forbidden: True => бросить ошибку при запретных словах

    Возвращает финальный перевод (строка).
    Исключения: RuntimeError если никакой движок не смог перевести.
    """

    start_time = time.time()
    src_lang = source_lang or "auto"
    logger.info(
        f"[perform_translation] text_len={len(text)} lang={src_lang}→{target_lang}, style={style}, chunking={allow_chunking}"
    )

    # 1) Проверяем кэш
    cached = get_translation_from_memory(db, text, src_lang, target_lang)
    if cached:
        logger.info("Перевод взят из кэша TranslationMemory.")
        return cached

    main_translation = None

    # 2) Сначала пробуем DeepL (если есть ключи), c разбивкой по абзацам
    if settings.DEEPL_API_KEY:
        try:
            logger.debug("Пробуем Deepl для основного перевода...")
            main_translation = await translate_with_deepl(
                text=text,
                source_lang=src_lang,
                target_lang=target_lang,
                style=style,
                chunk_size=chunk_size,
                attempts_on_error=1,
                # Новый параметр
                split_by_paragraphs=allow_chunking,
                join_with_newline=True,
                auto_detect_source=True
            )
            logger.info("DeepL перевод успешно выполнен.")
        except Exception as e:
            logger.warning(f"DeepL движок не сработал: {e}")

    # 3) Если Deepl не перевёл, пробуем Google (с abzaцным делением).
    if not main_translation and settings.GOOGLE_SERVICE_ACCOUNT_JSON:
        try:
            logger.debug("Пробуем Google движок (fallback)...")
            main_translation = await translate_with_google(
                text=text,
                source_lang=src_lang,
                target_lang=target_lang,
                style=style,
                chunk_size=chunk_size,
                join_with_newline=True,
                format_type="text",
                auto_detect_source=True,
                split_by_paragraphs=allow_chunking,
                attempts_on_error=1
            )
            logger.info("Google перевод успешно выполнен.")
        except Exception as e:
            logger.warning(f"Google движок не сработал: {e}")

    # Если ни Deepl, ни Google не дали результата
    if not main_translation:
        msg = "Ни Deepl, ни Google не смогли выполнить перевод."
        logger.error(msg)
        raise RuntimeError(msg)

    # 4) GPT-4 sense-check (если OPENAI_API_KEY)
    final_text = main_translation
    if settings.OPENAI_API_KEY:
        try:
            logger.debug(
                "Запуск GPT-4 для проверки/улучшения перевода (sense-check).")
            # Допустим, используем translate_with_gpt в special режиме "improve existing text"
            # или пишем новую функцию sense_check_with_gpt(…)
            final_text = await translate_with_gpt(
                text=main_translation,
                source_lang=src_lang,
                target_lang=target_lang,
                style=style,
                model="gpt-4",
                fallback_model=None,
                # В sense-check можно chunk'ить тоже (или нет)
                split_by_paragraphs=allow_chunking,
                chunk_size=chunk_size,
                # Если translator_gpt.py поддерживает такой "mode".
                mode="improve"
            )
            logger.info("GPT-4 sense-check успешно выполнен.")
        except Exception as gpt_err:
            logger.warning(
                f"GPT-4 sense-check не сработал: {gpt_err}. Оставляем текст как есть.")

    # 5) Постобработка
    try:
        final_text = postprocess_text(
            db=db,
            text=final_text,
            src_lang=src_lang,
            tgt_lang=target_lang,
            domain=domain,
            subdomain=subdomain,
            apply_punctuation_cleanup=True,
            use_smart_masking=postproc_smart_mask,
            throw_on_forbidden=postproc_throw_on_forbidden
        )
    except Exception as postproc_err:
        logger.error(f"Ошибка на этапе постобработки: {postproc_err}")
        raise RuntimeError("Postprocessing error") from postproc_err

    # 6) Сохраняем в кэш
    save_translation_to_memory(db, text, final_text, src_lang, target_lang)

    elapsed_sec = time.time() - start_time
    logger.info(
        f"Перевод завершён за {elapsed_sec:.2f} сек. Итоговая длина: {len(final_text)} символов.")
    return final_text
