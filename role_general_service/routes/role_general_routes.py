# routes/role_general_routes.py

from fastapi import APIRouter, HTTPException
from typing import Optional

# Импортируем модели Pydantic:
from models.request_models import (
    AnalyzeClientRequirementsRequest,
    GenerateFinalTextRequest,
    MarketingRequest,
    BlogPostRequest,
    SloganRequest,
    TranslationRequest,
    EmailSequenceRequest,
    SalesPageRequest,
    ProductDescriptionRequest,
    CustomPromptRequest,
)

# Допустим, логику «двухшаговой» генерации (анализ + итог) мы держим в logic.py:
from core.logic import (
    analyze_client_requirements,
    generate_final_text_from_analysis,
    generate_text_via_two_step,
    generate_text_via_three_step
)

# Допустим, маркетинговую логику/копирайтинг мы держим в marketing.py / copywriting.py:
from services.marketing import (
    generate_campaign_brief,
    generate_promotional_text,
    generate_brand_positioning,
    generate_social_media_post,
    generate_marketing_strategy_outline,
    generate_influencer_collaboration_pitch,
    generate_custom_marketing,
)

from services.copywriting import (
    generate_sales_page,
    generate_email_sequence,
    generate_product_description,
    generate_video_script,
    generate_faq_section,
    generate_testimonial,
    generate_custom_copywriting,
)

# Создаем роутер
router = APIRouter()

# -----------------------------------------------------------------------------
# 1. Двухшаговый / трёхшаговый сценарий: анализ ТЗ + генерация
# -----------------------------------------------------------------------------


@router.post("/analyze", summary="Анализ ТЗ", description="Анализирует текст ТЗ и возвращает JSON-структуру (type, style, length и т.д.)")
def analyze_tz(payload: AnalyzeClientRequirementsRequest):
    """
    Шаг 1: Анализирует ТЗ (техническое задание).
    Возвращает словарь (JSON), где определены:
    - type (marketing, blog_post, translation, slogan...)
    - style, language, length, extra_requirements, summary, recommendation...
    """
    result = analyze_client_requirements(payload.client_requirements)
    if "error" in result:
        raise HTTPException(status_code=400, detail=result["error"])
    return {"analysis_result": result}


@router.post("/generate_final", summary="Генерация итогового текста", description="Использует результат анализа, генерирует финальный текст.")
def generate_final_text_endpoint(payload: GenerateFinalTextRequest):
    """
    Шаг 2: Получив результат анализа (analysis_result), формирует итоговый текст.
    Опционально может использовать raw_text (например, для перевода).
    """
    # Здесь вы можете передать параметры (max_tokens, temperature) в функцию:
    final_text = generate_final_text_from_analysis(
        analysis_result=payload.analysis_result,
        raw_text=payload.raw_text
    )
    return {"result_text": final_text}


@router.post("/two_step_flow", summary="Двухшаговый сценарий (анализ -> генерация)", description="Запускает полный двухшаговый цикл (анализ ТЗ -> генерация).")
def two_step_flow(payload: AnalyzeClientRequirementsRequest):
    """
    Запускает полноценный «двухшаговый» сценарий:
    1) analyze_client_requirements
    2) generate_final_text_from_analysis
    """
    result_text = generate_text_via_two_step(payload.client_requirements)
    return {"result_text": result_text}


@router.post("/three_step_flow", summary="Трёхшаговый сценарий (анализ -> умный промпт -> генерация)", description="Запускает трёхшаговый цикл, если SMART_PROMPT_BUILDER включён.")
def three_step_flow(payload: AnalyzeClientRequirementsRequest):
    """
    Запускает «трёхшаговый» сценарий:
    1) analyze_client_requirements
    2) build_smart_prompt (если есть)
    3) финальная генерация
    """
    result_text = generate_text_via_three_step(payload.client_requirements)
    return {"result_text": result_text}

# -----------------------------------------------------------------------------
# 2. Прямые эндпоинты для конкретных задач (маркетинг, блог, перевод и т.д.)
# -----------------------------------------------------------------------------

#
# 2.1 Маркетинг
#


@router.post("/marketing/campaign_brief", summary="Создать маркетинговый бриф")
def create_campaign_brief(payload: dict):
    """
    Пример: создание маркетингового брифа.
    Для наглядности показываем, как можно принимать JSON напрямую или через Pydantic-модель.
    Но лучше создать отдельную Pydantic-модель (CampaignBriefRequest).
    """
    campaign_name = payload.get("campaign_name", "Campaign X")
    goals = payload.get("goals", [])
    target_audience = payload.get("target_audience", "Не указано")
    channels = payload.get("channels", [])
    brand_voice = payload.get("brand_voice", "professional")

    return {
        "result_text": generate_campaign_brief(
            campaign_name=campaign_name,
            goals=goals,
            target_audience=target_audience,
            channels=channels,
            brand_voice=brand_voice
        )
    }


@router.post("/marketing/promotional_text", summary="Короткий рекламный текст")
def create_promotional_text(payload: MarketingRequest):
    """
    Создаёт короткий рекламный (продающий) текст (промо).
    """
    result_text = generate_promotional_text(
        product_or_service=payload.product_or_service,
        promo_goal=payload.promo_goal,
        brand_voice=payload.brand_voice,
        max_tokens=payload.max_tokens,
        # temperature, top_p и т.д. при необходимости прокиньте из payload
    )
    return {"result_text": result_text}


@router.post("/marketing/brand_positioning", summary="Позиционирование бренда")
def brand_positioning_endpoint(payload: dict):
    """
    Создаёт описание позиционирования (brand_name, core_values, target_audience, competition).
    Здесь для упрощения сделан dict, но можете завести отдельный BrandPositioningRequest в request_models.py.
    """
    brand_name = payload["brand_name"]
    core_values = payload.get("core_values", [])
    target_audience = payload.get("target_audience", "Не указана")
    competition = payload.get("competition", None)
    brand_voice = payload.get("brand_voice", "professional")

    return {
        "result_text": generate_brand_positioning(
            brand_name=brand_name,
            core_values=core_values,
            target_audience=target_audience,
            competition=competition,
            brand_voice=brand_voice
        )
    }


@router.post("/marketing/social_media_post", summary="Пост в соцсети")
def social_media_post_endpoint(payload: dict):
    """
    Создаёт короткий пост для указанной платформы (FB, IG, LinkedIn...).
    """
    topic = payload["topic"]
    platform = payload["platform"]
    brand_voice = payload.get("brand_voice", "friendly")

    return {
        "result_text": generate_social_media_post(
            topic=topic,
            platform=platform,
            brand_voice=brand_voice
        )
    }


@router.post("/marketing/strategy", summary="Маркетинговая стратегия")
def marketing_strategy_endpoint(payload: dict):
    """
    Генерирует структуру маркетинговой стратегии: цели, бюджет, сроки, ЦА и т.д.
    """
    objective = payload["objective"]
    budget_range = payload["budget_range"]
    timeframe = payload["timeframe"]
    target_audience = payload["target_audience"]

    return {
        "result_text": generate_marketing_strategy_outline(
            objective=objective,
            budget_range=budget_range,
            timeframe=timeframe,
            target_audience=target_audience
        )
    }


@router.post("/marketing/influencer_pitch", summary="Питч инфлюенсеру")
def influencer_pitch_endpoint(payload: dict):
    """
    Письмо-обращение к инфлюенсеру (блогеру) о коллаборации.
    """
    brand_name = payload["brand_name"]
    influencer_type = payload["influencer_type"]
    collaboration_goal = payload["collaboration_goal"]

    return {
        "result_text": generate_influencer_collaboration_pitch(
            brand_name=brand_name,
            influencer_type=influencer_type,
            collaboration_goal=collaboration_goal
        )
    }


@router.post("/marketing/custom", summary="Кастомный маркетинговый запрос")
def custom_marketing_endpoint(payload: dict):
    """
    Любой произвольный маркетинговый запрос (custom_prompt).
    """
    custom_prompt = payload["custom_prompt"]
    system_role = payload.get(
        "system_role", "You are a marketing expert with a broad skill set.")

    return {
        "result_text": generate_custom_marketing(
            custom_prompt=custom_prompt,
            system_role=system_role
        )
    }


#
# 2.2 Копирайтинг (лендинги, email-кампании, описания, видео, FAQ, отзывы...)
#

@router.post("/copywriting/sales_page", summary="Продающая лендинговая страница")
def sales_page_endpoint(payload: SalesPageRequest):
    """
    Создаёт продающий текст лендинговой страницы.
    """
    result_text = generate_sales_page(
        product_name=payload.product_name,
        unique_selling_points=payload.unique_selling_points,
        target_audience=payload.target_audience,
        brand_voice=payload.brand_voice,
        max_tokens=payload.max_tokens,
        temperature=payload.temperature,
        # top_p, frequency_penalty, presence_penalty, ...
    )
    return {"result_text": result_text}


@router.post("/copywriting/email_sequence", summary="Серия email-писем")
def email_sequence_endpoint(payload: EmailSequenceRequest):
    """
    Генерирует серию (N) писем для email-кампании (цель, тон, etc.).
    """
    result_text = generate_email_sequence(
        campaign_goal=payload.campaign_goal,
        number_of_emails=payload.number_of_emails,
        brand_voice=payload.brand_voice,
        max_tokens=payload.max_tokens,
        temperature=payload.temperature
        # ...
    )
    return {"result_text": result_text}


@router.post("/copywriting/product_description", summary="Описание продукта")
def product_description_endpoint(payload: ProductDescriptionRequest):
    """
    Короткое продающее описание продукта.
    """
    result_text = generate_product_description(
        product_name=payload.product_name,
        features=payload.features,
        brand_voice=payload.brand_voice,
        max_tokens=payload.max_tokens,
        temperature=payload.temperature
        # ...
    )
    return {"result_text": result_text}


@router.post("/copywriting/video_script", summary="Сценарий видео")
def video_script_endpoint(payload: dict):
    """
    Генерирует сценарий видео (YouTube, промо-ролик, обучающий контент).
    """
    topic = payload["topic"]
    duration = payload.get("duration", "short")
    style = payload.get("style", "informative")
    max_tokens = payload.get("max_tokens", 500)

    result_text = generate_video_script(
        topic=topic,
        duration=duration,
        style=style,
        max_tokens=max_tokens
        # ...
    )
    return {"result_text": result_text}


@router.post("/copywriting/faq_section", summary="Раздел FAQ")
def faq_section_endpoint(payload: dict):
    """
    Генерирует блок FAQ для продукта/услуги.
    """
    product_or_service_name = payload["product_or_service_name"]
    possible_questions = payload.get("possible_questions", [])
    brand_voice = payload.get("brand_voice", "professional")
    max_tokens = payload.get("max_tokens", 400)

    result_text = generate_faq_section(
        product_or_service_name=product_or_service_name,
        possible_questions=possible_questions,
        brand_voice=brand_voice,
        max_tokens=max_tokens
        # ...
    )
    return {"result_text": result_text}


@router.post("/copywriting/testimonial", summary="Отзыв (testimonial)")
def testimonial_endpoint(payload: dict):
    """
    Генерирует текст отзыва о продукте/услуге.
    """
    product_or_service_name = payload["product_or_service_name"]
    user_type = payload.get("user_type", "обычный клиент")
    brand_voice = payload.get("brand_voice", "authentic")

    result_text = generate_testimonial(
        product_or_service_name=product_or_service_name,
        user_type=user_type,
        brand_voice=brand_voice
    )
    return {"result_text": result_text}


@router.post("/copywriting/custom", summary="Кастомный копирайтинг")
def custom_copywriting_endpoint(payload: dict):
    """
    Универсальная функция для произвольных запросов в копирайтинге.
    """
    custom_prompt = payload["custom_prompt"]
    system_role = payload.get(
        "system_role", "You are a professional marketing copywriter.")

    result_text = generate_custom_copywriting(
        custom_prompt=custom_prompt,
        system_role=system_role
    )
    return {"result_text": result_text}

# -----------------------------------------------------------------------------
# 3. Пример переводов, блога, слоганов (если используете их напрямую)
# -----------------------------------------------------------------------------


@router.post("/translation", summary="Перевод текста")
def translation_endpoint(payload: TranslationRequest):
    """
    Запрос на перевод текста.
    """
    # Предположим, у вас есть функция core.logic.generate_translation(...),
    # или copywriting.generate_translation(...)
    # Ниже псевдокод. Замените на свой реальный вызов.
    from core.logic import generate_translation

    result_text = generate_translation(
        text=payload.text,
        target_language=payload.target_language,
        max_tokens=payload.max_tokens,
        temperature=payload.temperature,
        top_p=payload.top_p,
        frequency_penalty=payload.frequency_penalty,
        presence_penalty=payload.presence_penalty
    )
    return {"result_text": result_text}


@router.post("/blog", summary="Блог-пост")
def blog_post_endpoint(payload: BlogPostRequest):
    """
    Генерация блог-поста (короткий, средний, длинный).
    """
    from core.logic import generate_blog_post
    result_text = generate_blog_post(
        topic=payload.topic,
        length=payload.length.value,  # Enum -> str, если нужно
        max_tokens=payload.max_tokens
        # + temperature, top_p, etc., если ваша логика это обрабатывает
    )
    return {"result_text": result_text}


@router.post("/slogan", summary="Рекламный слоган")
def slogan_endpoint(payload: SloganRequest):
    """
    Генерация рекламного слогана для бренда.
    """
    from core.logic import generate_ad_slogan
    result_text = generate_ad_slogan(
        brand_name=payload.brand_name,
        style=payload.style.value,
        max_tokens=payload.max_tokens
        # ...
    )
    return {"result_text": result_text}

# -----------------------------------------------------------------------------
# 4. Кастомный запрос на любой промпт (CustomPromptRequest)
# -----------------------------------------------------------------------------


@router.post("/custom_prompt", summary="Произвольный промпт")
def custom_prompt_endpoint(payload: CustomPromptRequest):
    """
    Принимает произвольный prompt (и system_role), передаёт в GPT.
    """
    from core.logic import generate_custom_text
    result_text = generate_custom_text(
        prompt=payload.custom_prompt,
        system_role=payload.system_role,
        max_tokens=payload.max_tokens if payload.max_tokens else 500
        # + temperature, etc.
    )
    return {"result_text": result_text}
