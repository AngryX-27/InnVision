"""
translator_google.py — усовершенствованный модуль для перевода текста через Google Cloud Translation API (REST).

Дополнения к прежней логике:
1) Разбиение текста по абзацам + дополнительное деление, если абзац > chunk_size.
2) Авто-детект исходного языка (source_lang="auto") — тогда не указываем source в payload.
3) Ретрай при 503/504/сетевых ошибках (с ограничением attempts_on_error).
4) Параметр format_type: "text" или "html", передаём в "format" Google API.
5) style: Google официально игнорирует, но логируем для совместимости.
6) Возможность гибко склеивать chunk’и (join_with_newline=True/False).

Прочие детали (7, 8, 9 пункты) не добавляем.
"""

from google.oauth2 import service_account
import google.auth.transport.requests
import google.auth
import logging
from typing import Optional, Dict, List, Union

import httpx
from fastapi import HTTPException

from translation_service.config import settings

logger = logging.getLogger(__name__)

GOOGLE_TRANSLATE_URL = "https://translation.googleapis.com/language/translate/v2"

# Импорты для сервис-аккаунта (Bearer-токен):


def split_into_paragraphs(text: str) -> List[str]:
    """
    Делим текст на абзацы по символу новой строки (\n).
    Пропускаем пустые абзацы (если несколько \n подряд).
    """
    raw_parts = text.split("\n")
    paragraphs = [p.strip() for p in raw_parts if p.strip()]
    return paragraphs


def basic_chunk_split(text: str, chunk_size: int) -> List[str]:
    """
    Если абзац длиной > chunk_size, разбиваем его на куски.
    """
    if len(text) <= chunk_size:
        return [text]

    result = []
    start = 0
    while start < len(text):
        end = min(start + chunk_size, len(text))
        chunk = text[start:end]
        result.append(chunk)
        start = end
    return result


def paragraph_based_chunks(text: str, chunk_size: int) -> List[str]:
    """
    Сначала делим текст по абзацам, 
    если абзац всё равно > chunk_size — режем basic_chunk_split.
    """
    paragraphs = split_into_paragraphs(text)
    final_chunks = []
    for p in paragraphs:
        if len(p) > chunk_size:
            final_chunks.extend(basic_chunk_split(p, chunk_size))
        else:
            final_chunks.append(p)
    return final_chunks


def prepare_google_payload(
    texts: List[str],
    source_lang: Optional[str],
    target_lang: str,
    format_type: str = "text",
    auto_detect_source: bool = True
) -> Dict:
    """
    Формирует JSON-пейлоад для Google Translate API:
      - "q": список строк
      - "target": target_lang
      - "format": "text" / "html"
      - (optionally) "source": <lowercase lang> (если не auto_detect_source)

    Если source_lang="auto" и auto_detect_source=True, не передаём "source".
    """
    payload = {
        "q": texts,
        "target": target_lang.lower(),
        "format": format_type
    }

    if source_lang and source_lang.lower() != "auto":
        payload["source"] = source_lang.lower()
    else:
        if not auto_detect_source:
            payload["source"] = "auto"

    return payload


def _get_bearer_token_from_service_account() -> str:
    """
    Загружаем JSON-файл сервисного аккаунта из settings.GOOGLE_SERVICE_ACCOUNT_JSON.
    Получаем credentials, обновляем (refresh) и возвращаем access_token.
    """
    if not settings.GOOGLE_SERVICE_ACCOUNT_JSON:
        logger.error("GOOGLE_SERVICE_ACCOUNT_JSON не указан.")
        raise HTTPException(
            status_code=500,
            detail="Google service account JSON is missing."
        )
    creds = service_account.Credentials.from_service_account_file(
        settings.GOOGLE_SERVICE_ACCOUNT_JSON,
        scopes=["https://www.googleapis.com/auth/cloud-platform"]
    )
    request = google.auth.transport.requests.Request()
    creds.refresh(request)
    return creds.token


async def call_google_api(payload: Dict, attempts: int = 1) -> List[str]:
    """
    Асинхронный вызов Google Cloud Translation API (v2),
    c retry при 503/504/сетевых ошибках.
    Возвращает список переведённых строк.
    Авторизация ТОЛЬКО через JSON сервисного аккаунта (Bearer-токен).
    """
    # Проверяем, что JSON-файл вообще есть
    if not settings.GOOGLE_SERVICE_ACCOUNT_JSON:
        logger.error(
            "Нет GOOGLE_SERVICE_ACCOUNT_JSON. Невозможно использовать Google Translate.")
        raise HTTPException(
            status_code=500, detail="No Google service account JSON found."
        )

    # Получаем Bearer-токен
    token = _get_bearer_token_from_service_account()
    headers = {"Authorization": f"Bearer {token}"}

    for attempt in range(1, attempts + 1):
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                logger.debug(
                    f"[Google attempt={attempt}] POST {GOOGLE_TRANSLATE_URL}, json={payload}")
                response = await client.post(
                    GOOGLE_TRANSLATE_URL,
                    json=payload,
                    headers=headers
                )
                response.raise_for_status()

            data = response.json()
            # Ожидаем:
            # {
            #   "data": {
            #       "translations": [
            #         {"translatedText": "..."},
            #         ...
            #       ]
            #   }
            # }
            translations = data.get("data", {}).get("translations")
            if not translations:
                logger.error(f"Нет 'translations' в ответе Google: {data}")
                raise HTTPException(
                    502, "Неверный формат ответа Google Translate"
                )

            results = []
            for item in translations:
                txt = item.get("translatedText")
                if not txt:
                    logger.error(f"Нет 'translatedText' в элементе: {item}")
                    raise HTTPException(
                        502, "Неверный формат ответа Google Translate"
                    )
                results.append(txt)

            return results

        except httpx.HTTPStatusError as http_err:
            code = http_err.response.status_code
            logger.error(
                f"Google Translate HTTP {code}: {http_err.response.text}"
            )
            if code in (503, 504) and attempt < attempts:
                logger.warning(f"Google {code}, retry attempt {attempt+1}...")
                continue
            raise HTTPException(
                502, f"Google Translate HTTP Error: {http_err.response.text}"
            ) from http_err

        except httpx.RequestError as req_err:
            logger.error(f"Сетевая ошибка Google: {req_err}")
            if attempt < attempts:
                logger.warning(
                    f"Retrying network error... attempt={attempt+1}"
                )
                continue
            raise HTTPException(
                502, "Сетевая ошибка при запросе к Google Translate"
            ) from req_err

        except Exception as e:
            logger.error(
                f"Непредвиденная ошибка Google Translate: {e}",
                exc_info=True
            )
            raise HTTPException(
                502, "Ошибка при работе с Google Translate"
            ) from e

    raise HTTPException(502, "Google Translate: все попытки исчерпаны.")


async def translate_with_google(
    text: str,
    source_lang: Optional[str],
    target_lang: str,
    style: Optional[Dict] = None,
    chunk_size: int = 3000,
    join_with_newline: bool = True,
    format_type: str = "text",
    auto_detect_source: bool = True,
    split_by_paragraphs: bool = True,
    attempts_on_error: int = 1
) -> str:
    """
    Основная функция перевода через Google Cloud Translate (v2) — ТОЛЬКО через JSON сервисного аккаунта.

    Параметры:
      - text: исходная строка
      - source_lang: "en", "ru", "auto" — если auto_detect_source=True и source_lang="auto", не передаём "source"
      - target_lang: напр. "en", "ru"
      - style: Google не поддерживает формальность, но мы логируем
      - chunk_size: длина одного куска (3000)
      - join_with_newline: склеиваем результат через "\n" (True) или без переносов (False)
      - format_type: "text" или "html"
      - auto_detect_source: если True и source_lang="auto", не указываем source
      - split_by_paragraphs: если True, сначала делим текст на абзацы (переводим каждый), 
                            если абзац > chunk_size, режем его
      - attempts_on_error: кол-во повторов при 503/504/сетевых ошибках

    Возвращает итоговый перевод (str).
    """
    text = text.strip()
    if not text:
        logger.debug("Пустая строка для перевода, возвращаем как есть.")
        return text

    # Логируем style (Google всё равно игнорирует).
    if style:
        logger.debug(
            f"Style (Google не поддерживает, просто логируем): {style}")

    # Разделяем текст на блоки
    if split_by_paragraphs:
        paragraphs = paragraph_based_chunks(text, chunk_size)
    else:
        paragraphs = basic_chunk_split(text, chunk_size)

    if len(paragraphs) == 1:
        # Один запрос
        payload = prepare_google_payload(
            [paragraphs[0]],
            source_lang=source_lang,
            target_lang=target_lang,
            format_type=format_type,
            auto_detect_source=auto_detect_source
        )
        logger.debug(f"Один запрос Google, length={len(paragraphs[0])}")
        translated_list = await call_google_api(payload, attempts=attempts_on_error)
        return translated_list[0] if translated_list else ""

    else:
        # Несколько абзацев/чанков
        logger.info(
            f"Разбили текст на {len(paragraphs)} блок(ов) (chunk_size={chunk_size}).")
        payload = prepare_google_payload(
            paragraphs,
            source_lang=source_lang,
            target_lang=target_lang,
            format_type=format_type,
            auto_detect_source=auto_detect_source
        )

        translated_list = await call_google_api(payload, attempts=attempts_on_error)

        if join_with_newline:
            final_text = "\n".join(translated_list)
        else:
            final_text = "".join(translated_list)

        return final_text.strip()
