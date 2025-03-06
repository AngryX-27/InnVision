"""
postprocessing.py — Модуль для постобработки переведённого текста.

Основные этапы:
1) Загрузка глоссария и «запрещённых» слов из БД.
2) Применение глоссария (с учётом domain / subdomain + игнорирование брендов).
3) Фильтрация/маскирование запрещённых слов (с расширенной логикой throw_on_forbidden).
4) (Опционально) Дополнительная стилистическая правка (пунктуация и т.п.).
5) Единая функция postprocess_text, вызывающая все шаги подряд.
"""

import logging
import re
from typing import List, Optional

from sqlalchemy.orm import Session

# Модели ORM (пример: GlossaryTerm, ForbiddenWord) хранятся в db.models
from translation_service.db.models import GlossaryTerm, ForbiddenWord

# Пример: при желании подгружаем общие настройки (например, чтобы проверить DEBUG)
from translation_service.config import settings

logger = logging.getLogger(__name__)

#######################################
# 1) ЗАГРУЗКА ГЛОССАРИЯ И ЗАПРЕЩЁННЫХ СЛОВ
#######################################


def load_glossary(
    db: Session,
    src_lang: str,
    tgt_lang: str,
    domain: Optional[str] = None,
    subdomain: Optional[str] = None
) -> List[GlossaryTerm]:
    """
    Загружает глоссарные термины (GlossaryTerm) для пары языков (src_lang -> tgt_lang).
    Фильтрация:
      - domain (например, "IT", "legal", "marketing")
      - subdomain (опционально, если нужно еще более точный отбор)
    """
    query = db.query(GlossaryTerm).filter_by(
        source_lang=src_lang, target_lang=tgt_lang)

    if domain:
        query = query.filter_by(domain=domain)

    # демонстрационный, если subdomain есть в модели — тогда фильтруем
    # (Предполагается, что GlossaryTerm у вас может иметь поле subdomain,
    #  иначе этот пример — просто иллюстрация)
    if subdomain:
        # query = query.filter_by(subdomain=subdomain)  # <- если в модели есть это поле
        pass

    return query.all()


def load_forbidden_words(db: Session) -> List[ForbiddenWord]:
    """
    Загружает список запрещённых слов (ForbiddenWord) из таблицы forbidden_words.
    Можно при желании фильтровать по языку, дате и т.п.
    """
    return db.query(ForbiddenWord).all()

#######################################
# 2) ПРИМЕНЕНИЕ ГЛОССАРИЯ (ЗАМЕНА ТЕРМИНОВ)
#######################################


def apply_glossary_terms(
    text: str,
    glossary: List[GlossaryTerm],
    ignore_brands_in_glossary: Optional[List[str]] = None
) -> str:
    """
    Заменяет вхождения term_source -> term_target (с учётом границ слова, регистр игнорируем).
    Используем regex, чтобы не затрагивать часть слов (r"\b(frontend)\b").

    Параметры:
      - text: исходный текст
      - glossary: список GlossaryTerm (после фильтрации domain/subdomain)
      - ignore_brands_in_glossary: бренды, которые НЕ нужно переводить (если term_source совпадает)

    Если ignore_brands_in_glossary=["Frontend"], то "Frontend" не будет заменен на "фронтенд".
    """
    if not glossary:
        return text

    if ignore_brands_in_glossary is None:
        ignore_brands_in_glossary = []

    result = text
    for item in glossary:
        # Если term_source среди игнорируемых брендов, пропускаем замену
        if item.term_source.lower() in [b.lower() for b in ignore_brands_in_glossary]:
            continue

        pattern = r"\b(" + re.escape(item.term_source) + r")\b"

        def replace_func(match):
            # Сохраняем, если хотим учитывать регистр первой буквы...
            # matched_word = match.group(1)
            return item.term_target

        result = re.sub(pattern, replace_func, result, flags=re.IGNORECASE)

    return result


#######################################
# 3) ФИЛЬТРАЦИЯ / МАСКИРОВАНИЕ ЗАПРЕЩЁННЫХ СЛОВ (расширено)
#######################################
def filter_forbidden_words(
    text: str,
    forbidden_list: List[ForbiddenWord],
    mask_char: str = "*",
    smart_mask: bool = False,
    ignore_brands: Optional[List[str]] = None,
    throw_on_forbidden: bool = False
) -> str:
    """
    Находим все вхождения запрещённых слов (без учёта регистра) и маскируем их,
    либо бросаем исключение, если throw_on_forbidden=True.

    Параметры:
      - text: исходный текст
      - forbidden_list: список ForbiddenWord
      - mask_char: символ для маскировки (по умолчанию '*')
      - smart_mask: если True, "B*****" (сохраняем первую букву)
      - ignore_brands: список слов (брендов), которые НЕ маскировать
      - throw_on_forbidden: если True, при обнаружении «плохого» слова бросаем ValueError (или HTTPException).
    """
    if not forbidden_list:
        return text

    if ignore_brands is None:
        ignore_brands = []

    result = text
    words_escaped = []
    for fw in forbidden_list:
        if fw.word.lower() not in (b.lower() for b in ignore_brands):
            words_escaped.append(re.escape(fw.word))

    if not words_escaped:
        return text

    pattern = r"\b(" + "|".join(words_escaped) + r")\b"

    def mask_func(match):
        matched_word = match.group(1)
        logger.warning(f"Обнаружено запрещённое слово: {matched_word}")

        if throw_on_forbidden:
            # Бросаем исключение, «ломаем» цепочку
            # В реальном коде можно HTTPException(400, detail=...)
            # или RuntimeError, как вам удобнее.
            raise ValueError(f"Forbidden word found: {matched_word}")

        if smart_mask:
            if len(matched_word) <= 2:
                return mask_char * len(matched_word)
            else:
                # Оставляем первую букву, остальные маскируем
                return matched_word[0] + (mask_char * (len(matched_word) - 1))
        else:
            return mask_char * len(matched_word)

    try:
        result = re.sub(pattern, mask_func, result, flags=re.IGNORECASE)
    except ValueError as e:
        # Перехватываем исключение из mask_func (throw_on_forbidden=True),
        # перекидываем дальше, чтобы прервать всё postprocess.
        raise e

    return result

#######################################
# 4) ДОПОЛНИТЕЛЬНАЯ ОЧИСТКА ПУНКТУАЦИИ
#######################################


def clean_punctuation(text: str) -> str:
    """
    Минимальная "очистка" пунктуации:
    - Убираем лишние пробелы перед знаками препинания.
    - Урезаем большие группы восклицательных знаков до 3.
    - Сжимаем двойные+ пробелы в один.
    """
    text = re.sub(r"\s+([,\.!?])", r"\1", text)
    text = re.sub(r"!{4,}", "!!!", text)
    text = re.sub(r"\s{2,}", " ", text)
    return text.strip()

#######################################
# 5) ЕДИНАЯ ФУНКЦИЯ POSTPROCESS_TEXT
#######################################


def postprocess_text(
    db: Session,
    text: str,
    src_lang: str,
    tgt_lang: str,
    domain: Optional[str] = None,
    subdomain: Optional[str] = None,
    apply_punctuation_cleanup: bool = True,
    use_smart_masking: bool = False,
    ignore_brands: Optional[List[str]] = None,
    ignore_brands_in_glossary: Optional[List[str]] = None,
    throw_on_forbidden: bool = False
) -> str:
    """
    Основная "точка входа" для постобработки перевода.
      1) Загрузка глоссария (фильтр по domain, subdomain).
      2) Загрузка запрещённых слов.
      3) Применение глоссария (учёт ignore_brands_in_glossary).
      4) Фильтрация/маскировка (или исключение) при forbidden words (throw_on_forbidden).
      5) Доп. очистка пунктуации, если apply_punctuation_cleanup.

    Параметры:
      - db: SQLAlchemy Session
      - text: исходный текст
      - src_lang, tgt_lang: языки
      - domain, subdomain: фильтры для глоссария
      - apply_punctuation_cleanup: включаем очистку знаков
      - use_smart_masking: сохраняем первую букву при маскировании
      - ignore_brands: бренды, которые НЕ маскируем (forbidden words)
      - ignore_brands_in_glossary: бренды, которые НЕ переводим
      - throw_on_forbidden: если True, при обнаружении «плохого» слова бросаем исключение.

    Возвращает "отполированный" текст или бросает исключение, если throw_on_forbidden=True.
    """

    # 1) Глоссарий
    glossary = load_glossary(db, src_lang, tgt_lang,
                             domain=domain, subdomain=subdomain)

    # 2) Запрещённые слова
    forbidden_list = load_forbidden_words(db)

    # 3) Применяем глоссарий (с учётом ignore_brands_in_glossary)
    processed = apply_glossary_terms(text, glossary, ignore_brands_in_glossary)

    # 4) Фильтруем / маскируем запрещённые слова (или бросаем исключение)
    processed = filter_forbidden_words(
        processed,
        forbidden_list,
        mask_char="*",
        smart_mask=use_smart_masking,
        ignore_brands=ignore_brands,
        throw_on_forbidden=throw_on_forbidden
    )

    # 5) Очистка пунктуации
    if apply_punctuation_cleanup:
        processed = clean_punctuation(processed)

    return processed


#######################################
# 6) ПРИМЕР ЛОКАЛЬНОГО ТЕСТА (если вызвать напрямую)
#######################################
if __name__ == "__main__":
    # Для демонстрации подменим загрузку данных (mock)
    class MockGlossaryTerm:
        def __init__(self, s, t):
            self.term_source = s
            self.term_target = t

    class MockForbiddenWord:
        def __init__(self, w):
            self.word = w

    mock_glossary = [
        MockGlossaryTerm("Frontend", "фронтенд"),
        MockGlossaryTerm("Backend", "бэкенд"),
    ]
    mock_forbidden = [
        MockForbiddenWord("badword"),
        MockForbiddenWord("forbidden"),
        MockForbiddenWord("secret"),
    ]

    def mock_load_glossary(*args, **kwargs):
        return mock_glossary

    def mock_load_forbidden_words(*args, **kwargs):
        return mock_forbidden

    # Подменяем реальные функции для демонстрации
    load_glossary = mock_load_glossary
    load_forbidden_words = mock_load_forbidden_words

    sample_text = " This is a BADWORD! A secret forbidden text about FRONTEND & BACKEND. "
    try:
        processed_text = postprocess_text(
            db=None,
            text=sample_text,
            src_lang="en",
            tgt_lang="ru",
            domain="IT",
            subdomain="SomeSubdomain",
            apply_punctuation_cleanup=True,
            use_smart_masking=True,
            # допустим, слово "BADWORD" - это «бренд», не маскируем
            ignore_brands=["BADWORD"],
            # «FRONTEND» - тоже бренд, не переводим в глоссарии
            ignore_brands_in_glossary=["Frontend"],
            throw_on_forbidden=False  # Если бы True, нашли бы "secret" и выбросили исключение
        )

        print("Исходный текст:\n", sample_text)
        print("Обработанный текст:\n", processed_text)

    except ValueError as e:
        print("Произошло исключение (throw_on_forbidden):", e)
