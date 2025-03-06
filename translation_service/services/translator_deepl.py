"""
translator_deepl.py — усовершенствованный модуль для перевода текста с помощью DeepL API.

Дополнительные фишки по сравнению с базовой версией:
1) Гибкое разбиение текста (можно включить «умное» деление по пробелам или абзацам).
2) Поддержка HTML-формата (format_type = "text" или "html").
3) Проверка поддерживаемых языков (DEEPL_SUPPORTED_LANGS).
4) Параметр auto_detect_source, если source_lang="auto".
5) Простая логика retrys при HTTP 503/504 (можно заменить на tenacity).
6) Продвинутое логирование (в DEBUG-уровне можно видеть заголовки ответа).
"""

import logging
from typing import Optional, Dict, List, Union

import httpx
from fastapi import HTTPException

from translation_service.config import settings

logger = logging.getLogger(__name__)

DEEPL_API_URL = "https://api.deepl.com/v2/translate"

# Пример (частичный) списка поддерживаемых языков DeepL (по состоянию на 2023-04).
# В реальном проекте лучше подгружать динамически из https://api.deepl.com/v2/languages,
# либо хранить в какой-то конфигурации.
DEEPL_SUPPORTED_LANGS = {
    "BG", "CS", "DA", "DE", "EL", "EN", "ES", "ET", "FI",
    "FR", "HU", "IT", "JA", "LT", "LV", "NL", "PL", "PT",
    "RO", "RU", "SK", "SL", "SV", "ZH"
}


def smart_split_into_chunks(text: str, chunk_size: int) -> List[str]:
    """
    "Умный" (условно) алгоритм, разбивающий текст на части максимум по chunk_size,
    но старающийся не разрывать слова посередине.

    1) Идём по тексту кусками ~chunk_size.
    2) Если попали на середину слова, откатываемся назад до последнего пробела.

    Можно усовершенствовать, учитывая абзацы, точки, знаки препинания и т.д.
    """

    chunks = []
    start = 0
    text_len = len(text)

    while start < text_len:
        end = min(start + chunk_size, text_len)
        # Если уже на конце
        if end == text_len:
            chunks.append(text[start:end])
            break

        # Если мы не в конце текста, «откатываемся» назад до пробела
        # чтобы не разрывать слово
        if text[end:end+1].isalnum():  # значит мы, скорее всего, в середине слова
            # идём назад, пока не встретим пробел
            backtrack = end
            while backtrack > start and not text[backtrack].isspace():
                backtrack -= 1
            if backtrack == start:
                # Не нашли пробел, значит придётся просто брать chunk_size
                pass
            else:
                end = backtrack

        chunk = text[start:end].strip()
        chunks.append(chunk)
        start = end

    # Удаляем пустые строки
    return [c for c in chunks if c]


def basic_split_into_chunks(text: str, chunk_size: int) -> List[str]:
    """
    Простая реализация: ровно по chunk_size символов, кроме
    последнего чанка, который может быть короче.
    """
    if len(text) <= chunk_size:
        return [text]

    res = []
    start = 0
    while start < len(text):
        end = start + chunk_size
        res.append(text[start:end])
        start = end
    return res


def prepare_deepl_payload(
    text: str,
    source_lang: Optional[str],
    target_lang: str,
    style: Optional[Dict] = None,
    format_type: str = "text",
    auto_detect_source: bool = True
) -> Dict[str, Union[str, Dict]]:
    """
    Формируем payload для DeepL /translate:

    Параметры:
    - text: исходная строка
    - source_lang, target_lang: ISO-коды (EN, DE, RU, ...)
    - style: например, {"formality": "more"}, можно расширить
    - format_type: "text" или "html", указывает DeepL, как трактовать текст
    - auto_detect_source: если True и source_lang="auto", не передаём source_lang

    Возвращаем dict, который отправим в data= / json= при POST.
    """
    # Валидируем target_lang
    if target_lang.upper() not in DEEPL_SUPPORTED_LANGS:
        logger.warning(
            f"Target lang {target_lang.upper()} не поддерживается DeepL.")
        # Можем здесь кидать ошибку, либо просто предупредить

    data = {
        "auth_key": settings.DEEPL_API_KEY,
        "text": text,
        "target_lang": target_lang.upper(),
        "tag_handling": "xml" if format_type == "html" else "plain",
    }

    # Исходный язык: если "auto" и auto_detect_source=True, не указываем source_lang
    if source_lang and source_lang.lower() != "auto":
        if source_lang.upper() not in DEEPL_SUPPORTED_LANGS:
            logger.warning(
                f"Source lang {source_lang.upper()} не в списке поддерживаемых?")
        data["source_lang"] = source_lang.upper()
    else:
        # Если explicitly "auto", и auto_detect_source=False,
        # можно указывать data["source_lang"] = "auto", но DeepL
        # обычно автоопределяет, когда source_lang не передаётся.
        pass

    # formality
    if style and "formality" in style:
        # valid: "less", "more", "default"
        data["formality"] = style["formality"]

    # формат: "html" или "text"
    # DeepL "officially" uses "tag_handling=xml/html" or "plain"
    # Указываем выше: tag_handling
    return data


async def call_deepl_api(data_params: Dict[str, Union[str, Dict]], attempts: int = 1) -> str:
    """
    Асинхронный вызов DeepL API.
    - data_params: payload для запроса
    - attempts: кол-во попыток при transient-ошибках (503, 504)

    При успешном ответе возвращаем переведённый текст (str).
    При ошибках — поднимаем HTTPException(502).
    """
    if not settings.DEEPL_API_KEY:
        logger.error("DEEPL_API_KEY отсутствует. Не можем использовать DeepL.")
        raise HTTPException(500, "DEEPL_API_KEY is missing.")

    # Пример retry: до N раз при 503 / 504
    for attempt in range(1, attempts + 1):
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                logger.debug(
                    f"[DeepL attempt={attempt}] POST {DEEPL_API_URL}, data={data_params}")
                response = await client.post(DEEPL_API_URL, data=data_params)
                response.raise_for_status()

            data = response.json()
            translations = data.get("translations")
            if not translations:
                logger.error(
                    f"Нет ключа 'translations' в ответе DeepL: {data}")
                raise HTTPException(502, "Неверный формат ответа от DeepL")

            translated_text = translations[0].get("text")
            if not translated_text:
                logger.error(f"Ответ DeepL не содержит 'text': {data}")
                raise HTTPException(502, "Неверный формат ответа от DeepL")

            # Успех
            return translated_text.strip()

        except httpx.HTTPStatusError as http_err:
            status_code = http_err.response.status_code
            logger.error(f"DeepL HTTP {status_code}: {http_err.response.text}")

            if status_code in (503, 504) and attempt < attempts:
                logger.warning(
                    f"DeepL {status_code}, попробуем ещё раз (attempt {attempt+1})...")
                continue
            raise HTTPException(
                502, f"DeepL HTTP Error: {http_err.response.text}") from http_err

        except httpx.RequestError as req_err:
            logger.error(f"Сетевая ошибка при обращении к DeepL: {req_err}")
            # Аналогично retry
            if attempt < attempts:
                logger.warning(
                    f"Retrying due to network error... (attempt {attempt+1})")
                continue
            raise HTTPException(
                502, "Сетевая ошибка при запросе к DeepL") from req_err

        except Exception as e:
            logger.error(
                f"Непредвиденная ошибка при работе с DeepL: {e}", exc_info=True)
            raise HTTPException(502, "Ошибка при работе с DeepL") from e

    # Если цикл вышел без return, значит неудачно
    raise HTTPException(502, "DeepL: все попытки исчерпаны.")


async def translate_with_deepl(
    text: str,
    source_lang: Optional[str],
    target_lang: str,
    style: Optional[Dict] = None,
    chunk_size: int = 3000,
    join_with_newline: bool = True,
    format_type: str = "text",
    auto_detect_source: bool = True,
    use_smart_chunking: bool = False,
    attempts_on_error: int = 1
) -> str:
    """
    Главная функция перевода через DeepL.

    Параметры:
      - text: исходная строка (может быть большой)
      - source_lang: "EN", "RU", "auto"...
      - target_lang: "EN", "RU"...
      - style: {"formality": "more"} и т.д.
      - chunk_size: ~3000 по умолчанию
      - join_with_newline: True => перевод склеиваем через "\n", иначе ""
      - format_type: "text" или "html"
      - auto_detect_source: если True и source_lang="auto", не передаём source_lang
      - use_smart_chunking: если True, используем умный алгоритм разбиения слов
      - attempts_on_error: кол-во retry при 503/504/сетевых ошибках

    Возвращает: итоговый перевод (str).
    """
    text = text.strip()
    if not text:
        logger.debug("Пустой текст, вернём как есть.")
        return text

    # style логируем
    if style:
        logger.debug(f"DeepL style: {style}")

    # Формируем список чанков
    if use_smart_chunking:
        chunks = smart_split_into_chunks(text, chunk_size)
    else:
        # базовый split
        chunks = basic_split_into_chunks(text, chunk_size)

    if len(chunks) == 1:
        # Один запрос к DeepL
        data_params = prepare_deepl_payload(
            text=chunks[0],
            source_lang=source_lang,
            target_lang=target_lang,
            style=style,
            format_type=format_type,
            auto_detect_source=auto_detect_source
        )
        logger.debug(f"Отправляем один запрос DeepL, length={len(chunks[0])}")
        result = await call_deepl_api(data_params, attempts=attempts_on_error)
        return result

    else:
        # Несколько чанков
        logger.info(
            f"Текст длиной {len(text)} символов, разбиваем на {len(chunks)} блок(ов).")
        translations = []
        for i, chunk in enumerate(chunks, start=1):
            logger.debug(
                f"DeepL перевод чанка #{i}/{len(chunks)}, length={len(chunk)}")
            data_params = prepare_deepl_payload(
                text=chunk,
                source_lang=source_lang,
                target_lang=target_lang,
                style=style,
                format_type=format_type,
                auto_detect_source=auto_detect_source
            )
            part_translated = await call_deepl_api(data_params, attempts=attempts_on_error)
            translations.append(part_translated)

        if join_with_newline:
            return "\n".join(translations).strip()
        else:
            return "".join(translations).strip()
