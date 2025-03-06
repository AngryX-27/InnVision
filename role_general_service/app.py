import os
import logging

from flask import Flask, request, jsonify
import openai

# Предположим, вы хотите подключать роуты из role_general_routes.py,
# если он реализован как Flask Blueprint (импортируем его).
# from routes.role_general_routes import role_general_blueprint

# -----------------------------------------------------------------------------
# Инициализация логирования
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# -----------------------------------------------------------------------------
# Загрузка ENV-настроек
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-3.5-turbo")

openai.api_key = OPENAI_API_KEY

DEFAULT_MAX_TOKENS = int(os.getenv("DEFAULT_MAX_TOKENS", 100))
DEFAULT_TEMPERATURE = float(os.getenv("DEFAULT_TEMPERATURE", 0.7))
DEFAULT_TOP_P = float(os.getenv("DEFAULT_TOP_P", 1.0))

# -----------------------------------------------------------------------------
# Создаём Flask-приложение
app = Flask(__name__)

# (Опционально) регистрируем blueprint, если у вас есть routes/role_general_routes.py:
# app.register_blueprint(role_general_blueprint, url_prefix="/api/role_general")

# -----------------------------------------------------------------------------
# Пример вспомогательной функции (адаптер для GPT),
# если вы не выносите её в gpt_client.py (но лучше выносить).


def call_gpt_chatcompletion(
    prompt: str,
    system_prompt: str = "You are a helpful assistant.",
    max_tokens: int = DEFAULT_MAX_TOKENS,
    temperature: float = DEFAULT_TEMPERATURE,
    top_p: float = DEFAULT_TOP_P,
    model: str = OPENAI_MODEL
) -> str:
    logger.info(
        f"[call_gpt_chatcompletion] model={model}, max_tokens={max_tokens}, temperature={temperature}, top_p={top_p}")
    try:
        response = openai.ChatCompletion.create(
            model=model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": prompt},
            ],
            max_tokens=max_tokens,
            temperature=temperature,
            top_p=top_p
        )
        return response["choices"][0]["message"]["content"].strip()

    except openai.RateLimitError as e:
        logger.warning(f"Rate limit reached: {e}")
        raise e
    except openai.APIConnectionError as e:
        logger.error(f"Connection error: {e}")
        raise e
    except Exception as e:
        logger.exception(f"Unhandled error in call_gpt_chatcompletion: {e}")
        raise e

# -----------------------------------------------------------------------------
# Эндпоинты
# -----------------------------------------------------------------------------


@app.route("/health", methods=["GET"])
def health_check():
    return jsonify({"status": "ok"}), 200


@app.route("/generate-text", methods=["POST"])
def generate_text():
    """
    Существующий эндпоинт: принимает {"topic", "max_tokens"?, "temperature"?, "top_p"?}
    и возвращает {"generated_text": "..."}.
    """
    data = request.get_json(force=True, silent=True) or {}
    topic = data.get("topic", "No topic provided")

    max_tokens = data.get("max_tokens", DEFAULT_MAX_TOKENS)
    temperature = data.get("temperature", DEFAULT_TEMPERATURE)
    top_p = data.get("top_p", DEFAULT_TOP_P)

    prompt_text = f"Напиши короткий текст на тему: {topic}"
    logger.info(
        f"[/generate-text] topic='{topic}', max_tokens={max_tokens}, temperature={temperature}, top_p={top_p}")

    try:
        generated_text = call_gpt_chatcompletion(
            prompt=prompt_text,
            system_prompt="You are a helpful assistant.",
            max_tokens=max_tokens,
            temperature=temperature,
            top_p=top_p,
            model=OPENAI_MODEL
        )
        return jsonify({"generated_text": generated_text}), 200

    except openai.RateLimitError:
        return jsonify({"error": "Rate limit reached. Try again later."}), 429
    except openai.APIConnectionError:
        return jsonify({"error": "Failed to connect to OpenAI API."}), 503
    except Exception as e:
        logger.exception(f"Unhandled error in /generate-text: {e}")
        return jsonify({"error": str(e)}), 500


# Пример добавления нового эндпоинта (или переноса из routes/role_general_routes.py):
@app.route("/analyze-tz", methods=["POST"])
def analyze_tz():
    """
    Демонстрация: Анализ ТЗ (technical assignment), возвращающий JSON-структуру.
    """
    data = request.get_json(force=True, silent=True) or {}
    tz_text = data.get("tz_text", "")

    system_prompt = "You are an advanced AI that analyzes requirements and returns structured JSON."
    user_prompt = f"""\
Вот ТЗ:
\"\"\"
{tz_text}
\"\"\"

1. Определи тип текста (marketing, blog_post, translation...), стиль, язык, extra_requirements.
2. Верни результат строго в формате JSON.
"""

    try:
        analysis_text = call_gpt_chatcompletion(
            prompt=user_prompt,
            system_prompt=system_prompt,
            max_tokens=500,
            temperature=0.0,
            top_p=1.0,
            model=OPENAI_MODEL
        )
        import json
        # Парсим JSON:
        parsed = {}
        error = None
        try:
            parsed = json.loads(analysis_text)
        except json.JSONDecodeError:
            error = "Invalid JSON from GPT"

        return jsonify({
            "analysis_result": parsed if not error else None,
            "raw_response": analysis_text,
            "error": error
        }), 200

    except openai.RateLimitError:
        return jsonify({"error": "Rate limit reached, try again later."}), 429
    except openai.APIConnectionError:
        return jsonify({"error": "Failed to connect to OpenAI API."}), 503
    except Exception as e:
        logger.exception(f"Unhandled error in /analyze-tz: {e}")
        return jsonify({"error": str(e)}), 500


# -----------------------------------------------------------------------------
# Точка входа
# -----------------------------------------------------------------------------

if __name__ == "__main__":
    port = int(os.getenv("PORT", 5001))
    debug_mode = os.getenv("DEBUG", "False").lower() == "true"
    app.run(host="0.0.0.0", port=port, debug=debug_mode)
