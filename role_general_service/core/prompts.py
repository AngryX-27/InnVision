"""
prompts.py

МАКСИМАЛЬНО РАСШИРЕННАЯ ВЕРСИЯ (v2.1 от 2025-01-19)

Содержит:
1) Системные промпты (SYSTEM_PROMPTS) + дополнительные фрагменты (PROMPT_FRAGMENTS).
2) Многоязычные версии системных промптов (LANG_PROMPTS).
3) Набор user templates (USER_PROMPTS) для разных задач (marketing, blog, SEO, translation, slogans, press_release и т.д.).
4) Примеры «умного» анализа ТЗ (TASK_ANALYSIS), генерации контента (TASK_GENERATION).
5) Пример «умного билдера» (SMART_PROMPT_BUILDER).

С помощью такой структуры вы можете:
- Легко расширять библиотеку промптов;
- Программно выбирать нужные «system/user» блоки по ключам;
- Добавлять мини-фрагменты (например, «избегай нецензурной лексики»);
- Хранить версии, вести документацию внутри одной структуры.
"""

# =============================================================================
# ------------------------- 1) БАЗОВАЯ СТРУКТУРА (В СЛОВАРЯХ) -----------------
# =============================================================================

PROMPT_FRAGMENTS = {
    "no_offensive": "Avoid using profanity, slurs, or offensive expressions.",
    "json_format_only": "Ответ верни строго в виде валидного JSON. Без пояснений.",
    "short_answer": "Будь краток и избегай лишних деталей."
    # ... можно добавлять больше фрагментов.
}

SYSTEM_PROMPTS = {
    # Базовый универсальный
    "base": """\
You are a helpful AI assistant with broad expertise in text generation.
Follow the instructions carefully and produce clear, coherent answers.
""",

    # Маркетинг
    "marketing": """\
You are an expert marketing copywriter with a deep understanding of consumer psychology.
Your task is to craft compelling, clear, and persuasive copy that captures the audience's attention.
""",

    # Блог
    "blog": """\
You are an experienced blog writer with an engaging storytelling style.
You know how to structure an article to keep readers interested.
""",

    # Переводы
    "translation": """\
You are a professional translator, fluent in multiple languages.
Your translations preserve the original meaning, style, and tone.
""",

    # Слоганы
    "slogan": """\
You are a creative branding expert who specializes in catchy, memorable slogans.
""",

    # Копирайтинг
    "copywriting": """\
You are a highly skilled copywriter, able to craft persuasive landing pages,
email campaigns, product descriptions, and promotional texts.
""",

    # SEO
    "seo": """\
You are an SEO specialist who creates content optimized for search engines
while maintaining readability and value for the user.
""",

    # Пресс-релизы
    "press_release": """\
You are a PR and communications expert who writes clear, newsworthy press releases
to attract media attention.
""",

    # Суммаризация
    "summary": """\
You are a summarization expert capable of condensing texts into clear, concise overviews
while preserving key details.
""",

    # Переписывание
    "rewriting": """\
You are a rewriting specialist who can take any source text and rewrite it
with clarity, coherence, and correct grammar, while retaining the original meaning.
""",

    # Видео-сценарии
    "video_script": """\
You are a skilled scriptwriter who can create concise, engaging outlines for videos
(YouTube, explainer videos, promo clips, etc.), including structure and key talking points.
""",

    # Соцсети
    "social_media": """\
You are a social media marketing expert who crafts short, attention-grabbing posts
adapted to the nuances of each platform (Facebook, Instagram, LinkedIn, etc.).
""",

    # QA
    "qa": """\
You are an automated QA assistant that checks text for grammar, style, policy compliance,
and the absence of disallowed content or words.
Return only your analysis and any flags.
Do not rewrite the entire text unless specifically requested.
"""
}

LANG_PROMPTS = {
    # Пример: для русскоязычных задач
    "ru": {
        "marketing": """Ты опытный маркетолог-копирайтер, владеешь психологией потребителей...""",
        "blog": """Ты блогер с опытом написания интересных статей на русском языке...""",
        # и т.д.
    },
    # Пример: для англоязычных задач
    "en": {
        "marketing": """You are an expert marketing copywriter for English-speaking audiences.""",
        "blog": """You are an experienced blog writer for English readers, adept at structuring articles..."""
        # ...
    }
}

# =============================================================================
# --------------------- 2) USER PROMPTS (TEMPLATES ДЛЯ ЗАДАЧ) ----------------
# =============================================================================
USER_PROMPTS = {
    # Маркетинг (продающие тексты)
    "MARKETING_TEMPLATE": """\
Напиши продающий текст для продукта '{product_name}' в стиле {tone}.
Укажи основные выгоды для клиента и сделай текст коротким, запоминающимся,
с чётким призывом к действию.
""",

    "PROMOTIONAL_TEMPLATE": """\
Напиши короткий рекламный текст (промо-объявление) для '{product_or_service}'
с учётом цели: {promo_goal}.
Стиль (brand voice): {brand_voice}.
Обязательно включи уникальное предложение (USP) и призыв к действию (CTA).
""",

    "EMAIL_CAMPAIGN_TEMPLATE": """\
Создай серию из {email_count} писем для email-кампании.
Цель кампании: {campaign_goal}.
Тон (brand voice): {brand_voice}.
В каждом письме укажи:
1) Заголовок
2) Ключевую идею / выгоду
3) Призыв к действию
4) Дружелюбную подпись
""",

    # Копирайтинг (лендинги, описания, FAQ)
    "LANDING_PAGE_TEMPLATE": """\
Напиши структуру продающей лендинговой страницы для продукта "{product_name}"
с учётом ключевых преимуществ:
{usp_list}.

Структура:
1) Яркий заголовок
2) Короткое описание продукта
3) Блок с преимуществами (USP)
4) Призыв к действию (CTA)
5) Финальное усиление (гарантии, отзывы и т.д.)

Тон: {brand_voice}.
""",

    "PRODUCT_DESCRIPTION_TEMPLATE": """\
Опиши продукт '{product_name}' так, чтобы читатель захотел его купить.
Важные характеристики: {features}.
Стиль: {brand_voice}.
Сделай текст около 2-3 абзацев, выделяя ключевые достоинства и решаемые проблемы.
""",

    "FAQ_TEMPLATE": """\
Составь раздел FAQ (Frequently Asked Questions) для продукта или услуги "{product_or_service}".
Количество вопросов: {num_questions}.

Формат:
Q: <Вопрос>
A: <Ответ>

Тон: {brand_voice}.
Включи конкретные выгоды, примеры и предупреди о возможных возражениях клиентов.
""",

    # Блог
    "BLOG_POST_TEMPLATE": """\
Напиши блог-пост на тему: '{topic}'.
Объём: {length_description}.

Структура:
1. Вступление (заинтересуй читателя)
2. Основная часть (раскрой тему, приведите примеры или факты)
3. Вывод (короткое резюме или призыв к действию)
""",

    "LONG_BLOG_POST_TEMPLATE": """\
Напиши развернутый блог-пост (5+ абзацев) на тему: "{topic}".
Учти SEO-оптимизацию (используй ключевые слова: {keywords}).
Поделись советами, фактами, статистикой, добавь подзаголовки.
Заверши выводом или призывом к действию.
""",

    # SEO
    "SEO_ARTICLE_TEMPLATE": """\
Напиши SEO-статью на тему: '{topic}' (примерно {word_count} слов).
Включи ключевые слова: {keywords} (упомяни каждый хотя бы 2-3 раза).
Структурируй текст с подзаголовками (H2, H3), списками, и сделай короткое заключение.
Стиль: {tone}.
""",

    "KEYWORD_OPTIMIZATION_TEMPLATE": """\
Улучши данный текст под поисковые запросы (SEO).
Текст (ниже):
\"\"\"
{original_text}
\"\"\"

Внедри ключевые слова: {keywords}, не нарушая естественность языка.
Сохрани общий смысл и стиль, избегай переспама ключевых слов.
""",

    # Перевод
    "TRANSLATION_TEMPLATE": """\
Переведи следующий текст на {target_language}:

{original_text}
""",

    "MULTILANGUAGE_TEMPLATE": """\
Нужно перевести этот текст на несколько языков: {languages}.
Текст:
\"\"\"
{original_text}
\"\"\"

Формат ответа:
{
  "Russian": "перевод...",
  "English": "translation...",
  ...
}
""",

    # Слоганы
    "SLOGAN_TEMPLATE": """\
Придумай {style} рекламный слоган для бренда '{brand_name}'.
Он должен быть коротким, цеплять внимание и легко запоминаться.
""",

    # Пресс-релиз
    "PRESS_RELEASE_TEMPLATE": """\
Напиши пресс-релиз об событии/продукте "{subject}".
Включи:
1) Заголовок (newsworthy, привлекающий внимание)
2) Вводный абзац (кто, что, где, когда)
3) Детали/цитаты/факты
4) Информацию о компании (background info)
5) Контактные данные

Стиль: формальный, информативный, чтобы СМИ могли легко использовать эту информацию.
""",

    # Summaries, rewriting
    "SUMMARY_TEMPLATE": """\
Сделай краткое резюме следующего текста (основные факты, идеи, выводы), сохранив ключевые детали:
\"\"\"
{original_text}
\"\"\"
""",

    "REWRITING_TEMPLATE": """\
Перепиши данный текст более понятным, стилистически улучшенным языком,
сохранив исходный смысл:
\"\"\"
{original_text}
\"\"\"
""",

    "EXPAND_TEMPLATE": """\
Возьми этот текст и расширь его, добавив детали, примеры, пояснения:
\"\"\"
{original_text}
\"\"\"
Сделай текст более содержательным, но не перегружай лишней «водой».
""",

    # Видео-сценарии
    "VIDEO_SCRIPT_TEMPLATE": """\
Напиши сценарий для видео на тему: '{topic}'.
Примерная длительность: {duration_desc}.
Стиль (Tone): {style}.

Структура сценария:
1) Короткое вступление (hook)
2) Основные пункты (с деталями, примерами)
3) Заключение (призыв к действию или финальная мысль)
""",

    # Соцсети
    "SOCIAL_MEDIA_POST_TEMPLATE": """\
Напиши короткий пост для {platform} на тему: '{topic}'.
Тон: {brand_voice}.
Добавь призыв к действию, хэштеги (если уместно) и вовлекающий вопрос.
""",

    # QA
    "QA_CHECK_TEMPLATE": """\
Проверь этот текст на грамматические ошибки, соответствие политике,
отсутствие запрещённых слов:
\"\"\"
{text_to_check}
\"\"\"

Верни результаты проверки в формате JSON:
{
  "grammar_issues": [...],
  "policy_violations": [...],
  "disallowed_words_found": [...],
  "overall_evaluation": "<ок/не ок>"
}
"""
}

# =============================================================================
# 3) ШАБЛОНЫ ДЛЯ ДВУХШАГОВОГО АНАЛИЗА ТЗ И ИТОГОВОЙ ГЕНЕРАЦИИ
# =============================================================================

TASK_ANALYSIS_SYSTEM_PROMPT = """\
You are an advanced AI capable of parsing detailed requirements (ТЗ) for text generation. 
Your goal is to read the client's instructions, extract key parameters (type of text, style, language, length, etc.), 
and propose the optimal approach to generate the final text.

Act like a consultant who precisely identifies what the client wants.
Do not produce the final text yet. Instead, focus on structuring the requirements.
"""

TASK_ANALYSIS_USER_PROMPT = """\
Вот ТЗ, которое прислал клиент:

\"\"\"
{client_requirements}
\"\"\"

1. Проанализируй ТЗ. Определи:
   - Тип запрашиваемого текста (marketing, blog_post, translation, slogan, press_release и т.д.)
   - Предполагаемый язык (русский, английский и т.д.)
   - Предполагаемый стиль (enthusiastic, formal, catchy, casual, technical и т.п.)
   - Объём (короткий, средний, длинный)
   - Доп. требования (ключевые слова, ограничения, аудитория, формат и т.д.)

2. Сформируй структурированный JSON-ответ с полями:
   "type": "<тип_текста>",
   "language": "<целевой_язык>",
   "style": "<стиль_или_тон>",
   "length": "<короткий/средний/длинный>",
   "extra_requirements": "<список/описание>",
   "summary": "<краткое резюме>",
   "recommendation": "<рекомендации>"

3. Не пиши итоговый текст! Нужно только анализ и структура (JSON).
"""

TASK_GENERATION_SYSTEM_PROMPT = """\
You are a specialized AI writer capable of generating any type of text 
(marketing copy, blog posts, translations, slogans, etc.) with high quality.
You already have a structured plan (JSON) from previous analysis.

Use that plan to decide how to craft the final text.
"""

TASK_GENERATION_USER_PROMPT = """\
Ниже — JSON-результат анализа ТЗ:

\"\"\"
{analysis_result_json}
\"\"\"

1. Используй данные (type, language, style, length, extra_requirements и т.д.) для оптимального подхода.
2. Сгенерируй итоговый текст, максимально соответствующий этим параметрам.
3. Соблюдай стиль, язык, формат и любые доп. требования.
4. Верни только итоговый текст (без лишних пояснений).
"""

# =============================================================================
# 4) «УМНЫЙ ПОДБОР» (SMART PROMPT BUILDER)
# =============================================================================

SMART_PROMPT_BUILDER_SYSTEM_PROMPT = """\
You are an advanced AI that can read the analysis of a client's technical assignment (ТЗ)
and decide which existing prompt (or combination) from our library is most suitable,
OR generate a new prompt from scratch if needed.

Your goal is to produce a single 'ready-to-use' user prompt that will yield the best result.
"""

SMART_PROMPT_BUILDER_USER_PROMPT = """\
Данные анализа ТЗ (JSON):
\"\"\"
{analysis_result_json}
\"\"\"

1. Исходя из "type", "language", "style", "extra_requirements", и т.д.,
   определи, какой из шаблонов подходит (marketing, blog, translation, и т.п.).
2. Если ни один из готовых шаблонов полностью не покрывает требования,
   скомбинируй несколько шаблонов или создай уникальный.
3. Собери итоговый "user prompt", в котором:
   - Описывается задача
   - Учитываются style, language, length и extra_requirements
   - Присутствуют необходимые поля (product_name, keywords, etc.)
4. Верни чистый prompt (только текст), без пояснений и без финального результата.
"""

# =============================================================================
# 5) ДОПОЛНИТЕЛЬНАЯ ИНФОРМАЦИЯ И ТЕСТЫ
# =============================================================================

SLOGAN_STYLES = {
    "catchy": "Короткий, запоминающийся, игривый слоган",
    "formal": "Солидный, официальный тон",
    "humorous": "Добавь элемент юмора для позитивных эмоций",
    "minimalistic": "Лаконичный, фокус на сути"
}

COMMON_ENDING = """\
Убедись, что текст звучит естественно и понятно для целевой аудитории.
"""

LENGTH_DESCRIPTIONS = {
    "short": "короткий текст (1-2 абзаца)",
    "medium": "средний (3-4 абзаца)",
    "long": "развернутый материал (5+ абзацев)"
}

TONE_STYLES = {
    "enthusiastic": "энергичный, воодушевляющий",
    "formal": "официальный, деловой",
    "casual": "непринуждённый, дружеский",
    "catchy": "цепляющий, запоминающийся",
    "technical": "технический, детальный"
}


# =============================================================================
# 6) ПРИМЕР «ПРОМПТ-ТЕСТА» (НЕ РЕАЛЬНЫЙ КОД ТЕСТА, А ИЛЛЮСТРАЦИЯ)
# =============================================================================

def _test_prompt_formatting():
    """
    Пример «тестовой» функции, которая проверяет, корректно ли форматируется
    один из шаблонов (например, MARKETING_TEMPLATE), и не содержит ли пропущенных
    полей {some_field}, которые мы не заполнили.

    В реальном проекте вы бы импортировали это в тестовый модуль (pytest) и делали assert.
    """
    template = USER_PROMPTS["MARKETING_TEMPLATE"]
    try:
        formatted = template.format(product_name="SuperWidget", tone="formal")
        # Проверяем, нет ли неформатированных {...}
        if "{" in formatted and "}" in formatted:
            print("WARNING: есть незаполненные поля в шаблоне!")
        else:
            print("Template formatting OK:", formatted)
    except KeyError as e:
        print("Error: Missing field in template:", e)


# При желании можно раскомментировать для проверки вручную:
# _test_prompt_formatting()
