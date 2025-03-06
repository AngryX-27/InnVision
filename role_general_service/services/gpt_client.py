"""
gpt_client.py

Обёртка над OpenAI ChatCompletion (GPT), обеспечивающая:
- Загрузку ключа и настроек из config/settings.py
- Повторы (retries) при Rate Limit / Connection Error (экспоненциальная задержка)
- Унифицированный метод generate_text_with_gpt для всего микросервиса
- Возможность включить логирование расхода токенов
- (Опционально) потоковый режим (stream) для частичного чтения ответов
"""

import time
import logging
import openai
from typing import Optional, List, Generator

from openai import OpenAIError, RateLimitError, APIConnectionError
from config.settings import get_settings

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

settings = get_settings()
openai.api_key = settings.OPENAI_API_KEY


def generate_text_with_gpt(
    prompt: str,
    system_role: str = "You are a helpful AI assistant.",
    model: Optional[str] = None,
    temperature: float = 0.7,
    max_tokens: int = 512,
    top_p: float = 1.0,
    frequency_penalty: float = 0.0,
    presence_penalty: float = 0.0,
    n: int = 1,
    retries: int = 3,
    backoff: float = 2.0,
    log_usage: bool = False,
    stream: bool = False
) -> str:
    """
    Обращается к OpenAI ChatCompletion, формирует результат на основе prompt и system_role.
    Если указываете model=None, по умолчанию используется модель из settings (OPENAI_MODEL).

    :param prompt: Текст, который передаётся роли "user".
    :param system_role: Текст, который передаётся роли "system" (задаёт контекст модели).
    :param model: Название модели (gpt-3.5-turbo, gpt-4 и т.д.). Если None, берём из settings.
    :param temperature: Параметр креативности (0.0..1.0).
    :param max_tokens: Максимальное число токенов в ответе.
    :param top_p: Параметр топ-п сэмплирования (0..1).
    :param frequency_penalty: Штраф за повторяемость слов (0..2).
    :param presence_penalty: Штраф за повторяемые темы (0..2).
    :param n: Сколько вариантов ответов сгенерировать (обычно 1).
    :param retries: Сколько раз повторять запрос при RateLimitError/ConnectionError.
    :param backoff: Базовая задержка (в секундах), растущая по экспоненте при ретраях.
    :param log_usage: Если True, будет логировать информацию об использовании токенов (prompt_tokens, completion_tokens).
    :param stream: Если True, включает потоковый вывод (stream=True) и возвращает контент частями (не для всех сценариев).
                   Но здесь для упрощения мы всё равно склеим поток в один итоговый текст, а не вернём генератор.
    :return: Сгенерированный текст (первый вариант).
    """
    if model is None:
        model = settings.OPENAI_MODEL  # Если не указали модель, берем из настроек

    attempt = 0
    # Результирующая строка для случая stream=True
    stream_collected = []

    while True:
        try:
            # Формируем базовые параметры для ChatCompletion
            request_params = dict(
                model=model,
                messages=[
                    {"role": "system", "content": system_role},
                    {"role": "user", "content": prompt}
                ],
                temperature=temperature,
                max_tokens=max_tokens,
                top_p=top_p,
                frequency_penalty=frequency_penalty,
                presence_penalty=presence_penalty,
                n=n,
                stream=stream  # опционально включаем потоковый вывод
            )

            # Делаем запрос
            if not stream:
                response = openai.ChatCompletion.create(**request_params)

                # Извлекаем контент первого ответа
                text_result = response["choices"][0]["message"]["content"].strip(
                )

                # Если включено логирование usage, выведем
                if log_usage and "usage" in response:
                    usage = response["usage"]
                    prompt_tokens = usage.get("prompt_tokens", 0)
                    completion_tokens = usage.get("completion_tokens", 0)
                    total_tokens = usage.get("total_tokens", 0)
                    logger.info(
                        f"[GPT] Usage: prompt={prompt_tokens}, completion={completion_tokens}, total={total_tokens}")

                return text_result

            else:
                # Потоковый режим (stream=True)
                response_iter = openai.ChatCompletion.create(**request_params)
                for part in response_iter:
                    if "choices" in part and len(part["choices"]) > 0:
                        delta = part["choices"][0]["delta"]
                        if "content" in delta:
                            stream_collected.append(delta["content"])

                return "".join(stream_collected).strip()

        except (RateLimitError, APIConnectionError) as e:
            attempt += 1
            if attempt > retries:
                logger.error(
                    f"[GPT] Превышено число попыток ({retries}) при запросе к GPT: {e}")
                raise e
            else:
                sleep_time = backoff ** attempt
                logger.warning(f"[GPT] Ошибка сети/лимита, попытка {attempt}/{retries}. "
                               f"Ждем {sleep_time:.1f} сек. Error: {e}")
                time.sleep(sleep_time)

        except OpenAIError as e:
            # Другие возможные ошибки OpenAI (APIError, InvalidRequestError и т.д.)
            logger.error(f"[GPT] OpenAIError: {e}")
            raise e

        except Exception as e:
            # Любая иная непредвиденная ошибка
            logger.exception(f"[GPT] Неизвестная ошибка: {e}")
            raise e
