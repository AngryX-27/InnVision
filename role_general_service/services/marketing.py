"""
marketing.py

Модуль для маркетинговых задач:
- Генерация брифа кампании
- Рекламные тексты (промо-объявления)
- Брендовое позиционирование
- Соцсетевые посты
- Маркетинговые стратегии
- Питч к инфлюенсеру
- Кастомные маркетинговые запросы

Использует:
- prompts (system + user) из core/prompts.py
- функцию generate_text_with_gpt из services/gpt_client.py
- настройки из config.settings
"""

from typing import List, Optional
import logging

from config.settings import get_settings
from services.gpt_client import generate_text_with_gpt
# Импортируем наши промпты
from core import prompts

logger = logging.getLogger(__name__)
settings = get_settings()


def generate_campaign_brief(
    campaign_name: str,
    goals: List[str],
    target_audience: str,
    channels: List[str],
    brand_voice: str = "professional",
    max_tokens: int = 600,
    temperature: float = 0.7,
    top_p: float = 1.0,
    frequency_penalty: float = 0.0,
    presence_penalty: float = 0.0,
    log_usage: bool = False
) -> str:
    """
    Генерирует краткий маркетинговый бриф (campaign brief) с учётом целей, целевой аудитории
    и планируемых каналов продвижения.

    :param campaign_name: Название/тема кампании (например, "Летняя распродажа 2025").
    :param goals: Список целей (повышение продаж, узнаваемость, продвижение нового продукта и т.д.).
    :param target_audience: Краткое описание целевой аудитории (например, "женщины 25-35, живущие в больших городах").
    :param channels: Каналы продвижения (соцсети, email, офлайн-баннеры, т.д.).
    :param brand_voice: Тон коммуникаций (professional, friendly, enthusiastic...).
    :param max_tokens: Лимит GPT-токенов для ответа.
    :param temperature: Креативность (0..1).
    :param top_p: top-p sampling (0..1).
    :param frequency_penalty: Штраф за повторяющиеся слова.
    :param presence_penalty: Штраф за повторные темы.
    :param log_usage: Логировать ли расход токенов.
    :return: Структурированный текст: цели, ключевые сообщения, каналы, примерный таймлайн, KPI.
    """
    # Формируем строки для целей и каналов
    goals_str = "; ".join(goals) if goals else "Нет конкретных целей"
    channels_str = ", ".join(channels) if channels else "Не указаны"

    # Достаём из prompts нужный user-шаблон
    user_prompt_template = prompts.USER_PROMPTS["CAMPAIGN_BRIEF_TEMPLATE"]
    user_prompt = user_prompt_template.format(
        campaign_name=campaign_name,
        goals_str=goals_str,
        target_audience=target_audience,
        channels_str=channels_str,
        brand_voice=brand_voice
    )

    # Вызываем GPT
    return generate_text_with_gpt(
        prompt=user_prompt,
        system_role=prompts.SYSTEM_PROMPTS["marketing_brief"],
        model=settings.OPENAI_MODEL,
        max_tokens=max_tokens,
        temperature=temperature,
        top_p=top_p,
        frequency_penalty=frequency_penalty,
        presence_penalty=presence_penalty,
        log_usage=log_usage
    )


def generate_promotional_text(
    product_or_service: str,
    promo_goal: str,
    brand_voice: str = "enthusiastic",
    max_tokens: int = 300,
    temperature: float = 0.7,
    top_p: float = 1.0,
    frequency_penalty: float = 0.0,
    presence_penalty: float = 0.0,
    log_usage: bool = False
) -> str:
    """
    Генерирует короткий рекламный текст (промо-объявление), ориентированный на достижение
    конкретной цели (усилить интерес к продукту, продать со скидкой, анонс новой функции и т.д.).

    :param product_or_service: Название/описание продукта или услуги.
    :param promo_goal: Цель рекламного текста.
    :param brand_voice: Стиль текста (enthusiastic, formal, playful и т.д.).
    :param max_tokens: Лимит на длину ответа GPT.
    :param temperature: Креативность.
    :param top_p: top-p sampling.
    :param frequency_penalty: Штраф за повторяемые слова.
    :param presence_penalty: Штраф за повторные темы.
    :param log_usage: Логировать ли usage токенов.
    :return: Короткий рекламный текст (можно использовать в соцсетях, баннерах или email-рассылке).
    """
    user_prompt_template = prompts.USER_PROMPTS["PROMOTIONAL_TEXT_TEMPLATE"]
    user_prompt = user_prompt_template.format(
        product_or_service=product_or_service,
        promo_goal=promo_goal,
        brand_voice=brand_voice
    )

    return generate_text_with_gpt(
        prompt=user_prompt,
        system_role=prompts.SYSTEM_PROMPTS["promotional_text"],
        model=settings.OPENAI_MODEL,
        max_tokens=max_tokens,
        temperature=temperature,
        top_p=top_p,
        frequency_penalty=frequency_penalty,
        presence_penalty=presence_penalty,
        log_usage=log_usage
    )


def generate_brand_positioning(
    brand_name: str,
    core_values: List[str],
    target_audience: str,
    competition: Optional[str] = None,
    brand_voice: str = "professional",
    max_tokens: int = 500,
    temperature: float = 0.7,
    top_p: float = 1.0,
    frequency_penalty: float = 0.0,
    presence_penalty: float = 0.0,
    log_usage: bool = False
) -> str:
    """
    Формирует текст о бренд-позиционировании, включая миссию, ценности,
    отличия от конкурентов, ключевые месседжи для ЦА.

    :param brand_name: Название бренда.
    :param core_values: Список ключевых ценностей (например, ['Innovation','Sustainability']).
    :param target_audience: Краткое описание целевой аудитории.
    :param competition: Упоминание конкурентов (по желанию).
    :param brand_voice: Тон (professional, enthusiastic, etc.).
    :param max_tokens: Лимит токенов.
    :param temperature: Креативность.
    :param top_p: top-p sampling.
    :param frequency_penalty: Штраф за повтор слов.
    :param presence_penalty: Штраф за повтор тем.
    :param log_usage: Логировать usage?
    :return: Структурированное описание позиционирования бренда.
    """
    core_values_str = ", ".join(core_values) if core_values else "не указаны"
    comp_str = f"\nНаши конкуренты: {competition}." if competition else ""

    user_prompt_template = prompts.USER_PROMPTS["BRAND_POSITIONING_TEMPLATE"]
    user_prompt = user_prompt_template.format(
        brand_name=brand_name,
        core_values_str=core_values_str,
        target_audience=target_audience,
        competition_str=comp_str
    )

    system_role = prompts.SYSTEM_PROMPTS["brand_positioning"]
    # Если хотите учесть brand_voice как-то отдельно, можно дополнить system_role
    # или user_prompt. Пока оставляем так.

    return generate_text_with_gpt(
        prompt=user_prompt,
        system_role=system_role,
        model=settings.OPENAI_MODEL,
        max_tokens=max_tokens,
        temperature=temperature,
        top_p=top_p,
        frequency_penalty=frequency_penalty,
        presence_penalty=presence_penalty,
        log_usage=log_usage
    )


def generate_social_media_post(
    topic: str,
    platform: str,
    brand_voice: str = "friendly",
    max_tokens: int = 200,
    temperature: float = 0.7,
    top_p: float = 1.0,
    frequency_penalty: float = 0.0,
    presence_penalty: float = 0.0,
    log_usage: bool = False
) -> str:
    """
    Генерирует пост для соцсети (FB, IG, LinkedIn, VK, и т.д.) по заданной теме.

    :param topic: Тема или инфоповод (акция, обзор, новость).
    :param platform: Целевая платформа (Facebook, Instagram, LinkedIn, VK, Telegram...).
    :param brand_voice: Тон (friendly, professional, casual...).
    :param max_tokens: Лимит ответа GPT.
    :param temperature: Креативность (0..1).
    :param top_p: top-p sampling.
    :param frequency_penalty: Штраф за повторяемые слова.
    :param presence_penalty: Штраф за повторные темы.
    :param log_usage: Логировать usage?
    :return: Текст поста (1-2 абзаца + призыв к действию, хэштеги).
    """
    user_prompt_template = prompts.USER_PROMPTS["SOCIAL_MEDIA_POST_TEMPLATE"]
    user_prompt = user_prompt_template.format(
        topic=topic,
        platform=platform,
        brand_voice=brand_voice
    )

    system_role = prompts.SYSTEM_PROMPTS["social_media"]

    return generate_text_with_gpt(
        prompt=user_prompt,
        system_role=system_role,
        model=settings.OPENAI_MODEL,
        max_tokens=max_tokens,
        temperature=temperature,
        top_p=top_p,
        frequency_penalty=frequency_penalty,
        presence_penalty=presence_penalty,
        log_usage=log_usage
    )


def generate_marketing_strategy_outline(
    objective: str,
    budget_range: str,
    timeframe: str,
    target_audience: str,
    max_tokens: int = 700,
    temperature: float = 0.7,
    top_p: float = 1.0,
    frequency_penalty: float = 0.0,
    presence_penalty: float = 0.0,
    log_usage: bool = False
) -> str:
    """
    Создаёт план маркетинговой стратегии:
    - Цель (objective)
    - Бюджет (budget_range)
    - Сроки (timeframe)
    - ЦА
    - Каналы, KPI, форматы контента, и т.д.

    :param objective: Главная цель (увеличение продаж, узнаваемость и т.д.).
    :param budget_range: Ориентировочный бюджет (например, '5-10k USD').
    :param timeframe: Сроки (Q1 2025).
    :param target_audience: Описание ЦА.
    :param max_tokens: Лимит GPT-токенов.
    :param temperature: Креативность.
    :param top_p: top-p sampling.
    :param frequency_penalty: Штраф за повтор слов.
    :param presence_penalty: Штраф за повтор тем.
    :param log_usage: Логировать usage?
    :return: Структурированный текст стратегии (пункты, подпункты).
    """
    user_prompt_template = prompts.USER_PROMPTS["MARKETING_STRATEGY_TEMPLATE"]
    user_prompt = user_prompt_template.format(
        objective=objective,
        budget_range=budget_range,
        timeframe=timeframe,
        target_audience=target_audience
    )

    system_role = prompts.SYSTEM_PROMPTS["marketing_strategy"]

    return generate_text_with_gpt(
        prompt=user_prompt,
        system_role=system_role,
        model=settings.OPENAI_MODEL,
        max_tokens=max_tokens,
        temperature=temperature,
        top_p=top_p,
        frequency_penalty=frequency_penalty,
        presence_penalty=presence_penalty,
        log_usage=log_usage
    )


def generate_influencer_collaboration_pitch(
    brand_name: str,
    influencer_type: str,
    collaboration_goal: str,
    max_tokens: int = 300,
    temperature: float = 0.7,
    top_p: float = 1.0,
    frequency_penalty: float = 0.0,
    presence_penalty: float = 0.0,
    log_usage: bool = False
) -> str:
    """
    Создаёт письмо / обращение к инфлюенсеру для коллаборации.

    :param brand_name: Название бренда/компании.
    :param influencer_type: Тип инфлюенсера (блогер о моде, спортсмен, tech-обзорщик...).
    :param collaboration_goal: Цель (продвижение нового продукта, улучшение имиджа, etc.).
    :param max_tokens: Лимит.
    :param temperature: Креативность.
    :param top_p: top-p sampling.
    :param frequency_penalty: Штраф за повтор слов.
    :param presence_penalty: Штраф за повтор тем.
    :param log_usage: Логировать usage?
    :return: Текст письма (pitch) для взаимовыгодного сотрудничества.
    """
    user_prompt_template = prompts.USER_PROMPTS["INFLUENCER_PITCH_TEMPLATE"]
    user_prompt = user_prompt_template.format(
        influencer_type=influencer_type,
        brand_name=brand_name,
        collaboration_goal=collaboration_goal
    )

    system_role = prompts.SYSTEM_PROMPTS["influencer_pitch"]

    return generate_text_with_gpt(
        prompt=user_prompt,
        system_role=system_role,
        model=settings.OPENAI_MODEL,
        max_tokens=max_tokens,
        temperature=temperature,
        top_p=top_p,
        frequency_penalty=frequency_penalty,
        presence_penalty=presence_penalty,
        log_usage=log_usage
    )


def generate_custom_marketing(
    custom_prompt: str,
    system_role: str = prompts.SYSTEM_PROMPTS["custom_marketing"],
    max_tokens: int = 500,
    temperature: float = 0.7,
    top_p: float = 1.0,
    frequency_penalty: float = 0.0,
    presence_penalty: float = 0.0,
    log_usage: bool = False
) -> str:
    """
    Универсальная функция для произвольных маркетинговых сценариев:
    Можно задать любой custom_prompt и, при необходимости, заменить system_role.

    :param custom_prompt: Произвольная инструкция (описание задачи).
    :param system_role: Системное сообщение (по умолчанию — "You are a marketing expert with a broad skill set.").
    :param max_tokens: Лимит.
    :param temperature: Креативность.
    :param top_p: top-p sampling.
    :param frequency_penalty: Штраф за повтор слов.
    :param presence_penalty: Штраф за повтор тем.
    :param log_usage: Логировать usage?
    :return: Сгенерированный GPT-текст на основе custom_prompt.
    """
    # Если хотим использовать заготовку для user_prompt:
    # user_prompt = prompts.USER_PROMPTS["CUSTOM_MARKETING_TEMPLATE"].format(custom_prompt=custom_prompt)
    # Но здесь передаём напрямую:
    user_prompt = custom_prompt

    return generate_text_with_gpt(
        prompt=user_prompt,
        system_role=system_role,
        model=settings.OPENAI_MODEL,
        max_tokens=max_tokens,
        temperature=temperature,
        top_p=top_p,
        frequency_penalty=frequency_penalty,
        presence_penalty=presence_penalty,
        log_usage=log_usage
    )
