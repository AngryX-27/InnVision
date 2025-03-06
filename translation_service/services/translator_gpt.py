"""
translator_gpt.py — усовершенствованный модуль для перевода через OpenAI GPT API.

Основные расширения:
1) Разбиение текста по абзацам + chunk_size (split_by_paragraphs=True).
2) Расширенная логика prompt (system message, user message), учитывающая style.
3) Ретраи (повторные попытки) при RateLimitError, ServiceUnavailableError и сетевых сбоях.
4) Возможность fallback c "gpt-4" на "gpt-3.5-turbo" (демо), если первая недоступна.
5) Более глубокая настройка (temperature, max_tokens, presence_penalty и т.д.).
"""

import logging
import asyncio
from typing import Optional, Dict, List, Union

import openai
from fastapi import HTTPException
from translation_service.config import settings

logger = logging.getLogger(__name__)

# Пример: можно считать это из settings, если хотите
DEFAULT_MODEL = "gpt-3.5-turbo"
FALLBACK_MODEL = "gpt-3.5-turbo"  # Если 'gpt-4' недоступна

################################
# 1) Разбиение текста на абзацы и/или чанки
################################


def split_into_paragraphs(text: str) -> List[str]:
    """
    Разделяем текст на абзацы (по '\n').
    Пропускаем пустые абзацы.
    """
    lines = text.split("\n")
    paragraphs = [p.strip() for p in lines if p.strip()]
    return paragraphs


def basic_chunk_split(text: str, chunk_size: int) -> List[str]:
    """
    Если абзац/строка > chunk_size, дополнительно режем.
    """
    if len(text) <= chunk_size:
        return [text]
    result = []
    start = 0
    while start < len(text):
        end = start + chunk_size
        chunk = text[start:end]
        result.append(chunk)
        start = end
    return result


def paragraph_based_chunks(text: str, chunk_size: int) -> List[str]:
    """
    Сначала разбиваем текст на абзацы.
    Если абзац > chunk_size, режем basic_chunk_split.
    """
    paragraphs = split_into_paragraphs(text)
    final_chunks = []
    for p in paragraphs:
        if len(p) > chunk_size:
            splitted = basic_chunk_split(p, chunk_size)
            final_chunks.extend(splitted)
        else:
            final_chunks.append(p)
    return final_chunks


################################
# 2) Формирование prompt
################################
def build_system_message(style: Optional[Dict] = None) -> str:
    """
    Генерируем system message для GPT, в котором можно
    прописать «строгие» правила (сохранить стиль, не выдумывать фактов, etc.).
    Можно расширять (учитывать domain, glossary).
    """
    base_system = "You are a professional translator. Preserve meaning, style, context."

    # Добавим тон / домен, если в style есть соответствующие ключи
    if style:
        tone = style.get("tone")
        domain = style.get("domain")
        if tone:
            base_system += f" The tone is {tone}."
        if domain:
            base_system += f" The domain is {domain}."

    return base_system


def build_user_prompt(
    text: str,
    source_lang: str,
    target_lang: str,
    style: Optional[Dict] = None
) -> str:
    """
    Формируем user-промт (messages[1]) для GPT, более подробный.
    Можно вставлять glossary / дополнительные инструкции (demonstration).
    """
    prompt = f"Переведи текст с языка '{source_lang}' на '{target_lang}'. Сохраняй смысл и контекст.\n"
    if style:
        style_str = ", ".join(
            f"{k}={v}" for k, v in style.items() if k not in ("tone", "domain"))
        if style_str:
            prompt += f"Учитывай доп. стиль: {style_str}.\n"

    prompt += f"\nТекст:\n{text}"
    return prompt


################################
# 3) Логика вызова GPT c retry
################################
async def call_gpt_api(
    system_msg: str,
    user_msg: str,
    model: str = DEFAULT_MODEL,
    temperature: float = 0.2,
    max_tokens: int = 2000,
    attempts: int = 1
) -> str:
    """
    Асинхронный вызов OpenAI ChatCompletion, c retry при
    RateLimitError, ServiceUnavailableError, сетевых ошибках.

    - system_msg: роль system
    - user_msg: роль user
    - model: gpt-3.5-turbo, gpt-4 и т.п.
    - temperature, max_tokens: настройки генерации
    - attempts: кол-во повторных попыток
    """
    if not settings.OPENAI_API_KEY:
        logger.error("OPENAI_API_KEY не найден, GPT-запрос невозможен.")
        raise HTTPException(500, "OPENAI_API_KEY is missing.")

    openai.api_key = settings.OPENAI_API_KEY

    for attempt in range(1, attempts + 1):
        try:
            logger.debug(
                f"GPT call attempt={attempt}, model={model}, system={len(system_msg)} chars, user={len(user_msg)} chars")

            resp = await openai.ChatCompletion.acreate(
                model=model,
                messages=[
                    {"role": "system", "content": system_msg},
                    {"role": "user", "content": user_msg}
                ],
                temperature=temperature,
                max_tokens=max_tokens
            )
            translated_text = resp["choices"][0]["message"]["content"]
            return translated_text.strip()

        except openai.error.RateLimitError as e:
            logger.warning(f"OpenAI RateLimitError: {e}")
            if attempt < attempts:
                logger.info(
                    f"Retrying RateLimitError... (attempt {attempt+1})")
                await asyncio.sleep(1.5)  # короткая пауза
                continue
            raise HTTPException(
                429, "OpenAI Rate Limit, no more attempts") from e

        except openai.error.APIConnectionError as e:
            logger.warning(f"OpenAI APIConnectionError: {e}")
            if attempt < attempts:
                logger.info(
                    f"Retrying APIConnectionError... (attempt {attempt+1})")
                await asyncio.sleep(1.5)
                continue
            raise HTTPException(502, "OpenAI API Connection Error") from e

        except openai.error.ServiceUnavailableError as e:
            logger.warning(f"OpenAI ServiceUnavailableError: {e}")
            if attempt < attempts:
                logger.info(
                    f"Retrying ServiceUnavailableError... (attempt {attempt+1})")
                await asyncio.sleep(2.0)
                continue
            raise HTTPException(502, "OpenAI Service Unavailable") from e

        except openai.error.OpenAIError as e:
            logger.error(f"OpenAIError: {e}")
            # InvalidRequestError, AuthenticationError, и т.д. — retry бессмыслен
            raise HTTPException(502, f"OpenAIError: {e}") from e

        except Exception as ex:
            logger.error(f"Непредвиденная ошибка GPT: {ex}", exc_info=True)
            raise HTTPException(500, "Internal Server Error (GPT)") from ex

    raise HTTPException(502, "GPT: все попытки исчерпаны.")


################################
# 4) «Главная» функция перевода
################################
async def translate_with_gpt(
    text: str,
    source_lang: str,
    target_lang: str,
    style: Optional[Dict] = None,
    model: str = DEFAULT_MODEL,
    fallback_model: Optional[str] = None,
    split_by_paragraphs: bool = False,
    chunk_size: int = 3000,
    attempts_on_error: int = 1,
    temperature: float = 0.2,
    max_tokens: int = 2000
) -> str:
    """
    Основная функция перевода через GPT с учётом всего расширенного функционала.

    Параметры:
      - text: входной текст
      - source_lang, target_lang: языки (строки)
      - style: словарь ({tone, domain, ...}), используем в prompt
      - model: основная модель (gpt-3.5-turbo / gpt-4)
      - fallback_model: если модель не работает (напр. gpt-4 недоступна), 
                       пробуем fallback (demonstration)
      - split_by_paragraphs: True => делим текст на абзацы, затем если абзац > chunk_size, 
                             режем. Иначе — грубое 3000.
      - chunk_size: размер для одного куска
      - attempts_on_error: кол-во повторов при RateLimitError, ServiceUnavailableError, ...
      - temperature, max_tokens: настройки GPT

    Возвращает str: итоговый перевод.
    """

    text = text.strip()
    if not text:
        logger.debug("Пустой текст для перевода, вернём исходный.")
        return text

    # 1) Разделяем на чанки
    if split_by_paragraphs:
        paragraphs = paragraph_based_chunks(text, chunk_size=chunk_size)
    else:
        paragraphs = basic_chunk_split(text, chunk_size=chunk_size)

    # 2) Если только 1 кусок, можно одним вызовом
    if len(paragraphs) == 1:
        system_msg = build_system_message(style)
        user_msg = build_user_prompt(
            paragraphs[0], source_lang, target_lang, style)
        # Пробуем вызвать основную модель
        try:
            translated = await call_gpt_api(
                system_msg=system_msg,
                user_msg=user_msg,
                model=model,
                temperature=temperature,
                max_tokens=max_tokens,
                attempts=attempts_on_error
            )
            return translated
        except HTTPException as e:
            if fallback_model and e.status_code in (429, 502):
                # Попробовать fallback
                logger.warning(
                    f"GPT model={model} недоступен, fallback => {fallback_model}")
                translated_fb = await call_gpt_api(
                    system_msg=system_msg,
                    user_msg=user_msg,
                    model=fallback_model,
                    temperature=temperature,
                    max_tokens=max_tokens,
                    attempts=attempts_on_error
                )
                return translated_fb
            raise e

    # 3) Если много чанков/абзацев => переводим по кускам
    logger.info(
        f"Текст длиной {len(text)} символов разбит на {len(paragraphs)} чанков.")
    results = []
    for i, chunk in enumerate(paragraphs, start=1):
        logger.debug(
            f"GPT перевод chunk #{i}/{len(paragraphs)}, length={len(chunk)}")
        system_msg = build_system_message(style)
        user_msg = build_user_prompt(chunk, source_lang, target_lang, style)

        # Пробуем основную модель
        try:
            part_result = await call_gpt_api(
                system_msg=system_msg,
                user_msg=user_msg,
                model=model,
                temperature=temperature,
                max_tokens=max_tokens,
                attempts=attempts_on_error
            )
            results.append(part_result)
        except HTTPException as e:
            if fallback_model and e.status_code in (429, 502):
                logger.warning(
                    f"GPT model={model} недоступен, fallback => {fallback_model}")
                fb_part = await call_gpt_api(
                    system_msg=system_msg,
                    user_msg=user_msg,
                    model=fallback_model,
                    temperature=temperature,
                    max_tokens=max_tokens,
                    attempts=attempts_on_error
                )
                results.append(fb_part)
            else:
                raise e

    final_text = "\n".join(results).strip()
    return final_text
