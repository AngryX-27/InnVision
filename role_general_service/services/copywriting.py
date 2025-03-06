"""
copywriting.py

Модуль, специализирующийся на копирайтинге (продающие лендинги,
email-кампании, описания товаров, видео-сценарии, FAQ, отзывы и т.д.).

1) Подтягивает нужные шаблоны (user/system prompts) из core/prompts.py.
2) Вызывает generate_text_with_gpt из services/gpt_client.py.
3) Предоставляет функции, которые можно использовать в роутерах (FastAPI/Flask)
   или в других частях микросервиса role_general_service.

Каждая функция принимает параметры:
- max_tokens (лимит длины ответа),
- temperature (0..1, креативность),
- top_p (0..1, top-p sampling),
- frequency_penalty (штраф за повтор слов),
- presence_penalty (штраф за повтор тем),
- log_usage (True/False, если хотите логировать расход токенов).
"""

from typing import List, Optional
import logging

from config.settings import get_settings
from services.gpt_client import generate_text_with_gpt
# Импортируем шаблоны и системные промпты (константы) из prompts.py
from core import prompts

logger = logging.getLogger(__name__)
settings = get_settings()


def generate_sales_page(
    product_name: str,
    unique_selling_points: List[str],
    target_audience: str = "широкая аудитория",
    brand_voice: str = "enthusiastic",
    max_tokens: int = 600,
    temperature: float = 0.7,
    top_p: float = 1.0,
    frequency_penalty: float = 0.0,
    presence_penalty: float = 0.0,
    log_usage: bool = False
) -> str:
    """
    Генерирует текст продающей веб-страницы (лендинга) для указанного продукта.

    Шаблоны:
      - user prompt:  prompts.SALES_PAGE_TEMPLATE
      - system role:  prompts.SALES_PAGE_SYSTEM_PROMPT
    """
    usp_str = "; ".join(
        unique_selling_points) if unique_selling_points else "Нет преимуществ"

    user_prompt = prompts.SALES_PAGE_TEMPLATE.format(
        product_name=product_name,
        target_audience=target_audience,
        usp_list=usp_str,
        brand_voice=brand_voice
    )

    return generate_text_with_gpt(
        prompt=user_prompt,
        system_role=prompts.SALES_PAGE_SYSTEM_PROMPT,
        model=settings.OPENAI_MODEL,
        max_tokens=max_tokens,
        temperature=temperature,
        top_p=top_p,
        frequency_penalty=frequency_penalty,
        presence_penalty=presence_penalty,
        log_usage=log_usage
    )


def generate_email_sequence(
    campaign_goal: str,
    number_of_emails: int = 3,
    brand_voice: str = "friendly",
    max_tokens: int = 800,
    temperature: float = 0.7,
    top_p: float = 1.0,
    frequency_penalty: float = 0.0,
    presence_penalty: float = 0.0,
    log_usage: bool = False
) -> str:
    """
    Генерирует серию email-писем (N штук) для заданной цели (продажи, онбординг, ретаргет и т.д.).

    Шаблоны:
      - user prompt:  prompts.EMAIL_SEQUENCE_TEMPLATE
      - system role:  prompts.EMAIL_SEQUENCE_SYSTEM_PROMPT
    """
    user_prompt = prompts.EMAIL_SEQUENCE_TEMPLATE.format(
        number_of_emails=number_of_emails,
        campaign_goal=campaign_goal,
        brand_voice=brand_voice
    )

    return generate_text_with_gpt(
        prompt=user_prompt,
        system_role=prompts.EMAIL_SEQUENCE_SYSTEM_PROMPT,
        model=settings.OPENAI_MODEL,
        max_tokens=max_tokens,
        temperature=temperature,
        top_p=top_p,
        frequency_penalty=frequency_penalty,
        presence_penalty=presence_penalty,
        log_usage=log_usage
    )


def generate_product_description(
    product_name: str,
    features: List[str],
    brand_voice: str = "enthusiastic",
    max_tokens: int = 300,
    temperature: float = 0.7,
    top_p: float = 1.0,
    frequency_penalty: float = 0.0,
    presence_penalty: float = 0.0,
    log_usage: bool = False
) -> str:
    """
    Генерирует короткое продающее описание товара (2-3 абзаца).

    Шаблоны:
      - user prompt:  prompts.PRODUCT_DESCRIPTION_TEMPLATE
      - system role:  prompts.PRODUCT_DESCRIPTION_SYSTEM_PROMPT
    """
    features_str = ", ".join(features) if features else "Нет особенностей"
    user_prompt = prompts.PRODUCT_DESCRIPTION_TEMPLATE.format(
        product_name=product_name,
        features=features_str,
        brand_voice=brand_voice
    )

    return generate_text_with_gpt(
        prompt=user_prompt,
        system_role=prompts.PRODUCT_DESCRIPTION_SYSTEM_PROMPT,
        model=settings.OPENAI_MODEL,
        max_tokens=max_tokens,
        temperature=temperature,
        top_p=top_p,
        frequency_penalty=frequency_penalty,
        presence_penalty=presence_penalty,
        log_usage=log_usage
    )


def generate_video_script(
    topic: str,
    duration: str = "short",
    style: str = "informative",
    max_tokens: int = 500,
    temperature: float = 0.7,
    top_p: float = 1.0,
    frequency_penalty: float = 0.0,
    presence_penalty: float = 0.0,
    log_usage: bool = False
) -> str:
    """
    Генерирует сценарий для короткого видео (YouTube, промо-ролик, обучающий контент и т.д.).

    Шаблоны:
      - user prompt:  prompts.VIDEO_SCRIPT_TEMPLATE
      - system role:  prompts.VIDEO_SCRIPT_SYSTEM_PROMPT
    """
    duration_map = {
        "short": "1-2 минуты",
        "medium": "3-5 минут",
        "long": "5+ минут"
    }
    duration_desc = duration_map.get(duration, "1-2 минуты")

    user_prompt = prompts.VIDEO_SCRIPT_TEMPLATE.format(
        topic=topic,
        duration_desc=duration_desc,
        style=style
    )

    return generate_text_with_gpt(
        prompt=user_prompt,
        system_role=prompts.VIDEO_SCRIPT_SYSTEM_PROMPT,
        model=settings.OPENAI_MODEL,
        max_tokens=max_tokens,
        temperature=temperature,
        top_p=top_p,
        frequency_penalty=frequency_penalty,
        presence_penalty=presence_penalty,
        log_usage=log_usage
    )


def generate_faq_section(
    product_or_service_name: str,
    possible_questions: Optional[List[str]] = None,
    brand_voice: str = "professional",
    max_tokens: int = 400,
    temperature: float = 0.7,
    top_p: float = 1.0,
    frequency_penalty: float = 0.0,
    presence_penalty: float = 0.0,
    log_usage: bool = False
) -> str:
    """
    Генерирует раздел FAQ (3-7 вопросов) для указанного продукта/услуги.

    Шаблоны:
      - user prompt:  prompts.FAQ_TEMPLATE
      - system role:  prompts.FAQ_SYSTEM_PROMPT
    """
    if possible_questions:
        joined_q = "\n".join(f"- {q}" for q in possible_questions)
        questions_part = f"Вот примерные вопросы:\n{joined_q}\n"
    else:
        questions_part = "Пусть GPT само подберёт 5-7 типовых вопросов.\n"

    user_prompt = prompts.FAQ_TEMPLATE.format(
        product_or_service_name=product_or_service_name,
        brand_voice=brand_voice,
        questions_part=questions_part
    )

    return generate_text_with_gpt(
        prompt=user_prompt,
        system_role=prompts.FAQ_SYSTEM_PROMPT,
        model=settings.OPENAI_MODEL,
        max_tokens=max_tokens,
        temperature=temperature,
        top_p=top_p,
        frequency_penalty=frequency_penalty,
        presence_penalty=presence_penalty,
        log_usage=log_usage
    )


def generate_testimonial(
    product_or_service_name: str,
    user_type: str = "обычный клиент",
    brand_voice: str = "authentic",
    max_tokens: int = 200,
    temperature: float = 0.7,
    top_p: float = 1.0,
    frequency_penalty: float = 0.0,
    presence_penalty: float = 0.0,
    log_usage: bool = False
) -> str:
    """
    Генерирует отзыв (testimonial) об использовании продукта/услуги.

    Шаблоны:
      - user prompt:  prompts.TESTIMONIAL_TEMPLATE
      - system role:  prompts.TESTIMONIAL_SYSTEM_PROMPT
    """
    user_prompt = prompts.TESTIMONIAL_TEMPLATE.format(
        product_or_service_name=product_or_service_name,
        user_type=user_type,
        brand_voice=brand_voice
    )

    return generate_text_with_gpt(
        prompt=user_prompt,
        system_role=prompts.TESTIMONIAL_SYSTEM_PROMPT,
        model=settings.OPENAI_MODEL,
        max_tokens=max_tokens,
        temperature=temperature,
        top_p=top_p,
        frequency_penalty=frequency_penalty,
        presence_penalty=presence_penalty,
        log_usage=log_usage
    )


def generate_custom_copywriting(
    custom_prompt: str,
    system_role: str = prompts.COPYWRITING_SYSTEM_PROMPT,
    max_tokens: int = 500,
    temperature: float = 0.7,
    top_p: float = 1.0,
    frequency_penalty: float = 0.0,
    presence_penalty: float = 0.0,
    log_usage: bool = False
) -> str:
    """
    Универсальная функция для произвольных сценариев копирайтинга.

    Шаблоны (опционально):
      - user prompt:  prompts.CUSTOM_COPYWRITING_TEMPLATE (можно, если хотите единый шаблон)
      - system role:  prompts.COPYWRITING_SYSTEM_PROMPT
    """
    # Если хотите использовать отдельный шаблон, можно сделать так:
    # user_prompt = prompts.CUSTOM_COPYWRITING_TEMPLATE.format(custom_prompt=custom_prompt)
    # Но здесь для простоты передаём напрямую custom_prompt.

    return generate_text_with_gpt(
        prompt=custom_prompt,
        system_role=system_role,
        model=settings.OPENAI_MODEL,
        max_tokens=max_tokens,
        temperature=temperature,
        top_p=top_p,
        frequency_penalty=frequency_penalty,
        presence_penalty=presence_penalty,
        log_usage=log_usage
    )
