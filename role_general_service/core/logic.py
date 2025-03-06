# core/logic.py

import json
import logging
from typing import Any, Dict, Optional

from config.settings import get_settings
from services.gpt_client import generate_text_with_gpt
from core import prompts

logger = logging.getLogger(__name__)
settings = get_settings()

# ---------------------------------------------------------------------------
# 1. Функции прямой генерации (маркетинг, блог, слоган, перевод, кастом)
# ---------------------------------------------------------------------------


def generate_marketing_text(
    product_name: str,
    tone: str = "enthusiastic",
    max_tokens: int = 300
) -> str:
    """
    Генерирует маркетинговый (продающий) текст для продукта.
    """
    prompt = (
        f"Напиши короткий продающий текст для продукта '{product_name}' "
        f"в тоне {tone}. Сделай акцент на выгодах для клиента."
    )
    return generate_text_with_gpt(
        prompt=prompt,
        system_role=prompts.MARKETING_SYSTEM_PROMPT,
        model=settings.OPENAI_MODEL,
        max_tokens=max_tokens
    )


def generate_blog_post(
    topic: str,
    length: str = "short",
    max_tokens: int = 512
) -> str:
    """
    Генерирует блог-пост по заданной теме (short, medium, long).
    """
    length_map = {
        "short": "короткий пост (1-2 абзаца)",
        "medium": "средний пост (3-5 абзацев)",
        "long": "подробный пост (6+ абзацев)"
    }
    chosen_length_desc = length_map.get(length, length_map["medium"])

    prompt = (
        f"Напиши {chosen_length_desc} на тему '{topic}'. "
        "Структурируй текст, упомяни факты или примеры, в конце сделай вывод."
    )
    return generate_text_with_gpt(
        prompt=prompt,
        system_role=prompts.BLOG_SYSTEM_PROMPT,
        model=settings.OPENAI_MODEL,
        max_tokens=max_tokens
    )


def generate_ad_slogan(
    brand_name: str,
    style: str = "catchy",
    max_tokens: int = 60
) -> str:
    """
    Генерирует рекламный слоган для бренда.
    """
    prompt = (
        f"Придумай {style} рекламный слоган для бренда '{brand_name}'. "
        "Слоган должен быть коротким и легко запоминаться."
    )
    return generate_text_with_gpt(
        prompt=prompt,
        system_role=prompts.SLOGAN_SYSTEM_PROMPT,
        model=settings.OPENAI_MODEL,
        max_tokens=max_tokens
    )


def generate_translation(
    text: str,
    target_language: str = "English",
    max_tokens: int = 256
) -> str:
    """
    Генерирует перевод заданного текста на целевой язык.
    """
    prompt = (
        f"Переведи следующий текст на {target_language}:\n\n"
        f"{text}"
    )
    return generate_text_with_gpt(
        prompt=prompt,
        system_role=prompts.TRANSLATION_SYSTEM_PROMPT,
        model=settings.OPENAI_MODEL,
        max_tokens=max_tokens
    )


def generate_custom_text(
    user_prompt: str,
    system_role: str = prompts.CUSTOM_SYSTEM_PROMPT,
    max_tokens: int = 300
) -> str:
    """
    Универсальная функция, если требуется произвольный (кастомный) промпт.
    """
    return generate_text_with_gpt(
        prompt=user_prompt,
        system_role=system_role,
        model=settings.OPENAI_MODEL,
        max_tokens=max_tokens
    )


# ---------------------------------------------------------------------------
# 2. Двухшаговый сценарий: (1) анализ ТЗ → (2) генерация
# ---------------------------------------------------------------------------

def analyze_client_requirements(client_requirements: str) -> Dict[str, Any]:
    """
    Шаг 1: Анализ ТЗ при помощи TASK_ANALYSIS_SYSTEM_PROMPT + TASK_ANALYSIS_USER_PROMPT.
    Ожидаем, что GPT вернёт валидный JSON со структурой:
    {
      "type": "marketing"/"blog_post"/"translation"/"slogan"/...,
      "language": "Russian"/"English"/...,
      "style": "enthusiastic"/...,
      "length": "short"/"medium"/"long",
      "extra_requirements": "...",
      "summary": "...",
      "recommendation": "..."
    }
    В случае проблемы парсинга JSON — возвращаем {"error": "..."}.
    """
    system_prompt = prompts.TASK_ANALYSIS_SYSTEM_PROMPT
    user_prompt = prompts.TASK_ANALYSIS_USER_PROMPT.format(
        client_requirements=client_requirements)

    try:
        response_text = generate_text_with_gpt(
            prompt=user_prompt,
            system_role=system_prompt,
            model=settings.OPENAI_MODEL,
            max_tokens=800
        )
        analysis = json.loads(response_text)
        if not isinstance(analysis, dict):
            return {"error": "GPT вернул не объект JSON", "raw_response": response_text}
        return analysis

    except json.JSONDecodeError as e:
        logger.warning(f"Не удалось распарсить JSON при анализе ТЗ: {e}")
        return {"error": "Invalid JSON from GPT"}
    except Exception as e:
        logger.exception(f"Ошибка при анализе ТЗ: {e}")
        return {"error": str(e)}


def generate_final_text_from_analysis(
    analysis_result: Dict[str, Any],
    raw_text: Optional[str] = None
) -> str:
    """
    Шаг 2: Генерация итогового текста на основе результатов анализа.
    Если "type" = marketing/blog_post/slogan/translation, вызываем соответствующие функции.
    Если неизвестен — fallback к generate_custom_text.
    :param analysis_result: результат анализирующего шага (dict).
    :param raw_text: если нужно использовать исходный текст (напр. для переводов).
    """
    if "error" in analysis_result:
        return f"Ошибка анализа: {analysis_result.get('error')}"

    text_type = analysis_result.get("type", "unknown")
    style = analysis_result.get("style", "enthusiastic")
    language = analysis_result.get("language", "Russian")
    length = analysis_result.get("length", "medium")
    extra_req = analysis_result.get("extra_requirements", "")
    summary = analysis_result.get("summary", "")

    # Простейший match
    if text_type == "marketing":
        product_name = parse_product_name_from(extra_req, default="MyProduct")
        return generate_marketing_text(product_name, tone=style)

    elif text_type == "blog_post":
        topic = summary if summary else "Без темы"
        return generate_blog_post(topic, length=length)

    elif text_type == "slogan":
        brand_name = parse_brand_name_from(extra_req, default="CompanyX")
        return generate_ad_slogan(brand_name, style=style)

    elif text_type == "translation":
        text_to_translate = raw_text or "Исходный текст не передан"
        return generate_translation(text_to_translate, target_language=language)

    else:
        # Если неизвестный тип
        custom_prompt = (
            f"Тип контента: {text_type}. Неизвестен конкретный шаблон.\n"
            f"Попробуй создать текст на основе анализа:\n{analysis_result}"
        )
        return generate_custom_text(custom_prompt)


def parse_product_name_from(extra_req: str, default="MyProduct") -> str:
    """
    Пример простой функции для извлечения product_name из поля extra_requirements.
    Если не нашли, возвращаем default.
    Можно парсить JSON, если extra_requirements = '{"product_name": "..."}'
    или искать по шаблону (ключ=значение).
    """
    # Демонстрация: если extra_req — это JSON-строка
    try:
        parsed = json.loads(extra_req)
        if isinstance(parsed, dict) and "product_name" in parsed:
            return parsed["product_name"]
    except:
        pass
    return default


def parse_brand_name_from(extra_req: str, default="MyBrand") -> str:
    """
    Аналогичный метод для извлечения brand_name, если нужно для слогана и т.д.
    """
    try:
        parsed = json.loads(extra_req)
        if isinstance(parsed, dict) and "brand_name" in parsed:
            return parsed["brand_name"]
    except:
        pass
    return default


# ---------------------------------------------------------------------------
# 3. «Умный» подбор промпта (опциональный трёхшаговый сценарий)
# ---------------------------------------------------------------------------

def build_smart_prompt(analysis_result: Dict[str, Any]) -> str:
    """
    Шаг 2 (альтернативный): «Умный» подбор (или генерация) промпта на основании анализа.
    Использует SMART_PROMPT_BUILDER_SYSTEM_PROMPT и SMART_PROMPT_BUILDER_USER_PROMPT из prompts.py,
    если в проекте предусмотрен такой сценарий.
    Возвращает готовый user-prompt.
    """
    if hasattr(prompts, "SMART_PROMPT_BUILDER_SYSTEM_PROMPT") and hasattr(prompts, "SMART_PROMPT_BUILDER_USER_PROMPT"):
        # Если эти промпты действительно определены в prompts.py
        system_prompt = prompts.SMART_PROMPT_BUILDER_SYSTEM_PROMPT
        user_prompt = prompts.SMART_PROMPT_BUILDER_USER_PROMPT.format(
            analysis_result_json=json.dumps(
                analysis_result, ensure_ascii=False)
        )
        try:
            response_text = generate_text_with_gpt(
                prompt=user_prompt,
                system_role=system_prompt,
                model=settings.OPENAI_MODEL,
                max_tokens=1200
            )
            return response_text.strip()

        except Exception as e:
            logger.exception(f"Ошибка при build_smart_prompt: {e}")
            return f"Ошибка при build_smart_prompt: {e}"
    else:
        # Если в prompts.py нет этих промптов, возвращаем заглушку
        return "Не настроена логика SMART_PROMPT_BUILDER в prompts.py"


def generate_text_via_three_step(
    client_requirements: str,
    raw_text: Optional[str] = None
) -> str:
    """
    Трёхшаговый сценарий:
      1. analyze_client_requirements
      2. build_smart_prompt (создать «user prompt» на основе анализа)
      3. финальный вызов GPT (передаём system=BASE_SYSTEM_PROMPT, user=smart_prompt).
    """
    analysis = analyze_client_requirements(client_requirements)
    if "error" in analysis:
        return f"Ошибка анализа: {analysis['error']}"

    smart_prompt = build_smart_prompt(analysis)
    if "Ошибка" in smart_prompt or "error" in smart_prompt.lower():
        # fallback — если умный промпт не сработал, просто генерируем финальный текст без него
        logger.warning(
            "Не удалось построить умный промпт. Переходим к generate_final_text_from_analysis.")
        return generate_final_text_from_analysis(analysis, raw_text=raw_text)
    else:
        # Вызываем GPT «напрямую» с тем промптом, который вернул build_smart_prompt
        try:
            result = generate_text_with_gpt(
                prompt=smart_prompt,
                system_role=prompts.BASE_SYSTEM_PROMPT if hasattr(
                    prompts, "BASE_SYSTEM_PROMPT") else "You are a helpful AI assistant.",
                max_tokens=800
            )
            return result.strip()
        except Exception as e:
            logger.exception(
                f"Ошибка при финальном вызове GPT в трехшаговом сценарии: {e}")
            return f"Ошибка: {e}"


# ---------------------------------------------------------------------------
# 4. Универсальная обёртка (двухшаговая) для упрощённого сценария
# ---------------------------------------------------------------------------

def generate_text_via_two_step(
    client_requirements: str,
    raw_text: Optional[str] = None
) -> str:
    """
    Упрощённая «двухшаговая» обёртка:
      1) analyze_client_requirements
      2) generate_final_text_from_analysis
    """
    analysis = analyze_client_requirements(client_requirements)
    return generate_final_text_from_analysis(analysis, raw_text=raw_text)


# ---------------------------------------------------------------------------
# Пример использования (необязательно, вы можете удалить этот блок)
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    # Небольшая демонстрация
    test_req = (
        "Нужно написать блог-пост на тему 'Преимущества работы в стартапах'. "
        "Я хочу формат средней длины, стиль не слишком формальный, язык — русский. "
        "Возможно, упомянуть пару примеров из реального опыта."
    )
    print("--- ДВУХШАГОВЫЙ СЦЕНАРИЙ ---")
    result_text = generate_text_via_two_step(test_req)
    print("Результат:\n", result_text)

    print("\n--- ТРЁХШАГОВЫЙ СЦЕНАРИЙ (если есть SMART_PROMPT_BUILDER) ---")
    result_text_3 = generate_text_via_three_step(test_req)
    print("Результат:\n", result_text_3)
