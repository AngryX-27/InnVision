"""
aggregator_service/services/gpt_service.py

Расширенная версия GPTService с дополнительными возможностями:
1. Поддержка нескольких API-ключей (pool) и fallback при RateLimitError.
2. Хуки before_request и after_request для кастомной логики.
3. Раздельные методы _build_request_payload, _parse_response для читабельности.
4. Улучшенная работа с токенами:
   - enable_token_count_check (True/False)
   - Возможность суммаризации предыдущих сообщений вместо простого обрезания (summarize_old_messages=True).
5. Гибкая конфигурация retry (exponential backoff, max_retry_delay).
6. Простое in-memory LRU-кэширование (cache_enabled, cache_size).
7. Расширенное логгирование с помощью structlog (при желании можно совмещать с logging).
8. Дополнительная обработка OpenAIError (400-500 статусы, переключение модели и ключей).

Автор: (ваша команда/имя)
"""

import os
import time
import json
import math
import logging
import openai
import structlog
import tiktoken
from typing import List, Dict, Optional, Any, Callable, Union, Tuple
from functools import lru_cache
from datetime import datetime
from requests.exceptions import Timeout
from openai import RateLimitError, APIError, OpenAIError

###############################################################################
# СТРУКТУРА ДЛЯ ХРАНЕНИЯ НЕСКОЛЬКИХ API-КЛЮЧЕЙ
###############################################################################


class APIKeyPool:
    """
    Простой пул ключей (список). При RateLimitError можно переключаться на другой ключ.
    """

    def __init__(self, api_keys: List[str]):
        self.api_keys = api_keys
        self.index = 0  # Текущий индекс

    def get_current_key(self) -> str:
        if not self.api_keys:
            return ""
        return self.api_keys[self.index]

    def switch_key(self):
        """
        Переключаемся на следующий ключ в списке.
        Если дошли до конца — возвращаемся к 0.
        """
        if not self.api_keys:
            return
        self.index = (self.index + 1) % len(self.api_keys)

    def __len__(self):
        return len(self.api_keys)


###############################################################################
# ОСНОВНОЙ КЛАСС GPTService
###############################################################################
class GPTService:
    """
    Класс, инкапсулирующий всю логику работы с OpenAI ChatCompletion, с расширенными функциями:
      - Мульти-ключ (fallback).
      - Хуки before_request, after_request.
      - Раздельные методы для формирования запроса и парсинга ответа.
      - Расширенное логгирование.
      - Гибкая работа с токенами (обрезка/суммаризация).
      - Кэширование результатов.
    """

    def __init__(
        self,
        api_keys: Optional[List[str]] = None,
        model: Optional[str] = None,
        temperature: float = 0.7,
        max_tokens: int = 200,
        retry_count: int = 3,
        retry_delay: int = 3,
        use_exponential_backoff: bool = False,
        max_retry_delay: Optional[int] = None,
        top_p: float = 1.0,
        presence_penalty: float = 0.0,
        frequency_penalty: float = 0.0,
        logger: Optional[Union[logging.Logger,
                               structlog.stdlib.BoundLogger]] = None,
        enable_token_count_check: bool = False,
        token_limit: int = 4096,
        summarize_old_messages: bool = True,
        summary_prompt: str = (
            "Please summarize the following conversation in a concise manner, preserving key points:\n"
        ),
        cache_enabled: bool = False,
        cache_size: int = 128,
        fallback_models: Optional[List[str]] = None,
    ):
        """
        :param api_keys: Список ключей OpenAI (для fallback при rate-limit).
                         Если не задан, пытаемся взять из окружения OPENAI_API_KEY.
        :param model: Модель по умолчанию (gpt-3.5-turbo, gpt-4, ...).
        :param temperature: Параметр температуры (0.0-2.0).
        :param max_tokens: Максимальное кол-во токенов на ответ.
        :param retry_count: Кол-во повторных попыток при ошибках.
        :param retry_delay: Базовая задержка между повторами (сек).
        :param use_exponential_backoff: Если True, delay *= 2 при каждой неудаче (до max_retry_delay).
        :param max_retry_delay: Предельная задержка, если exponential backoff включён.
        :param top_p: top_p выборка.
        :param presence_penalty: presence_penalty.
        :param frequency_penalty: frequency_penalty.
        :param logger: Можно передать structlog-логгер или logging.Logger.
        :param enable_token_count_check: Если True, проверяем кол-во токенов (prompt+max_tokens).
        :param token_limit: Лимит по токенам (например, 4096 для gpt-3.5).
        :param summarize_old_messages: Если True, при превышении лимита вызываем GPT для "суммаризации" старых сообщений, 
                                       вместо простого обрезания.
        :param summary_prompt: Промпт, используемый для суммаризации.
        :param cache_enabled: Если True, включаем простое LRU-кэширование на уровне питоновских функций.
        :param cache_size: Размер LRU-кэша (кол-во уникальных запросов).
        :param fallback_models: Список дополнительных моделей для переключения при ошибках (например, ["gpt-4", "gpt-3.5-turbo"]).
        """
        # Инициализация пула ключей
        if not api_keys:
            env_key = os.getenv("OPENAI_API_KEY", "")
            self.api_key_pool = APIKeyPool([env_key] if env_key else [])
        else:
            self.api_key_pool = APIKeyPool(api_keys)

        # Текущая модель
        if not model:
            self.model = os.getenv("GPT_MODEL", "gpt-3.5-turbo")
        else:
            self.model = model

        # fallback-модели (если нужно переключаться при ошибках)
        self.fallback_models = fallback_models or []

        # Основные параметры
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.retry_count = retry_count
        self.retry_delay = retry_delay
        self.use_exponential_backoff = use_exponential_backoff
        self.max_retry_delay = max_retry_delay
        self.top_p = top_p
        self.presence_penalty = presence_penalty
        self.frequency_penalty = frequency_penalty

        # Логгер
        if logger:
            self.logger = logger
        else:
            # Если structlog не настроен, делаем стандартный logging
            _logger = logging.getLogger("GPTServiceAdvanced")
            if not _logger.handlers:
                _logger.setLevel(logging.INFO)
                handler = logging.StreamHandler()
                handler.setFormatter(logging.Formatter(
                    "[%(asctime)s] %(levelname)s %(name)s: %(message)s"))
                _logger.addHandler(handler)
            self.logger = _logger

        # Токены
        self.enable_token_count_check = enable_token_count_check
        self.token_limit = token_limit
        self.summarize_old_messages = summarize_old_messages
        self.summary_prompt = summary_prompt

        # Кэширование
        self.cache_enabled = cache_enabled
        self.cache_size = cache_size
        if cache_enabled:
            self._cache_decorator = lru_cache(maxsize=cache_size)
        else:
            self._cache_decorator = lambda f: f

        # Установим начальный ключ
        self._apply_api_key(self.api_key_pool.get_current_key())

############################################################################
# ПУБЛИЧНЫЙ МЕТОД для запроса ChatCompletion
############################################################################


def chat_completion(
    self,
    messages: List[Dict[str, str]],
    user_id: Optional[str] = None
) -> str:
    """
    Основной метод обращения к ChatCompletion.
    :param messages: Список словарей {"role": "...", "content": "..."}.
    :param user_id: Необязательный ID пользователя (для логирования, метрик).
    :return: Текст ответа от ассистента.
    """
    if self.cache_enabled:
        # Преобразуем список сообщений в строку для формирования ключа
        messages_str = json.dumps(messages, sort_keys=True)
        # Ключ кэша — кортеж (все сообщения в JSON, текущая модель)
        cache_key = (messages_str, self.model)
        return self._chat_completion_cached(cache_key, user_id)
    else:
        return self._chat_completion_impl(messages, user_id)


def _chat_completion_cached(
    self,
    cache_key: Tuple[str, str],
    user_id: Optional[str]
) -> str:
    """
    Метод, в который мы передаём уже сформированный cache_key.
    Если кэш включён, он обёрнут lru_cache при инициализации класса.
    """
    messages_json, model = cache_key
    messages = json.loads(messages_json)
    return self._chat_completion_impl(messages, user_id)


def _chat_completion_impl(
    self,
    messages: List[Dict[str, str]],
    user_id: Optional[str] = None
) -> str:
    """
    Реальная логика вызова OpenAI (ChatCompletion).
    Обрабатывает повторы, переключение ключей, моделей, и т.д.
    """
    # before_request
    self.before_request(messages, user_id)

    # (При необходимости проверяем лимиты токенов)
    if self.enable_token_count_check:
        messages = self._check_and_adjust_messages(messages)

    delay = self.retry_delay
    current_model = self.model
    last_error = None

    for attempt in range(self.retry_count):
        try:
            payload = self._build_request_payload(messages, current_model)
            response = openai.ChatCompletion.create(**payload)
            assistant_msg = self._parse_response(response)
            # after_request: success
            self.after_request(messages, assistant_msg, user_id)
            return assistant_msg

        except RateLimitError as re:
            self.logger.warning(
                "RateLimitError",
                attempt=attempt+1,
                max_attempts=self.retry_count,
                model=current_model,
                error=str(re),
                user_id=user_id
            )
            last_error = re
            # Попробуем переключить ключ
            if len(self.api_key_pool) > 1:
                self.api_key_pool.switch_key()
                self._apply_api_key(self.api_key_pool.get_current_key())
                self.logger.info(
                    "Switched to another API key due to rate limit.")
            else:
                self.logger.info("No alternate API key available.")

            # Попробуем переключить модель
            if self.fallback_models:
                next_model = self._get_next_fallback_model(current_model)
                if next_model:
                    current_model = next_model
                    self.logger.info(f"Switched model to {next_model}")

            if attempt < self.retry_count - 1:
                delay = self._apply_backoff(delay)
                time.sleep(delay)
            else:
                break

        except (Timeout, APIError, OpenAIError) as oe:
            self.logger.warning(
                "OpenAIError",
                attempt=attempt+1,
                max_attempts=self.retry_count,
                model=current_model,
                error=str(oe),
                user_id=user_id
            )
            last_error = oe
            # Попробуем переключить модель/ключ, если это 5xx
            if isinstance(oe, APIError) and 500 <= oe.http_status < 600:
                if self.fallback_models:
                    next_model = self._get_next_fallback_model(current_model)
                    if next_model:
                        current_model = next_model
                        self.logger.info(f"Switched model to {next_model}")

            if attempt < self.retry_count - 1:
                delay = self._apply_backoff(delay)
                time.sleep(delay)
            else:
                break

        except Exception as e:
            self.logger.warning(
                "UnexpectedException",
                attempt=attempt+1,
                max_attempts=self.retry_count,
                model=current_model,
                error=str(e),
                user_id=user_id
            )
            last_error = e
            if attempt < self.retry_count - 1:
                delay = self._apply_backoff(delay)
                time.sleep(delay)
            else:
                break

    msg_error = f"(Ошибка при вызове ChatCompletion: {last_error})" if last_error else "(Неизвестная ошибка)"
    self.after_request(messages, msg_error, user_id, error=True)
    return msg_error

    ############################################################################
    # HOOKS: before_request, after_request
    ############################################################################

    def before_request(self, messages: List[Dict[str, str]], user_id: Optional[str]):
        """
        Вызывается перед отправкой запроса в OpenAI. Можно переопределить.
        """
        self.logger.debug("before_request", user_id=user_id,
                          messages_count=len(messages))

    def after_request(
        self,
        messages: List[Dict[str, str]],
        result_text: str,
        user_id: Optional[str],
        error: bool = False
    ):
        """
        Вызывается после получения результата (или ошибки).
        """
        if error:
            self.logger.error("after_request_error",
                              user_id=user_id, result_text=result_text[:80])
        else:
            self.logger.debug("after_request_success",
                              user_id=user_id, result_text=result_text[:80])

    ############################################################################
    # СЛУЖЕБНЫЕ МЕТОДЫ: СБОР ПЕЙЛОАДА, ПАРСИНГ ОТВЕТА
    ############################################################################
    def _build_request_payload(self, messages: List[Dict[str, str]], model: str) -> dict:
        """
        Формирует словарь (payload) для openai.ChatCompletion.create
        """
        return {
            "model": model,
            "messages": messages,
            "max_tokens": self.max_tokens,
            "temperature": self.temperature,
            "top_p": self.top_p,
            "presence_penalty": self.presence_penalty,
            "frequency_penalty": self.frequency_penalty
        }

    def _parse_response(self, response: Any) -> str:
        """
        Выделяем текст ассистента из ответа.
        """
        return response["choices"][0]["message"]["content"]

    def _apply_api_key(self, key: str):
        openai.api_key = key
        if not key:
            self.logger.warning(
                "GPTService: пустой API-ключ, вызовы OpenAI будут ошибочны."
            )

    def _apply_backoff(self, current_delay: float) -> float:
        if self.use_exponential_backoff:
            new_delay = current_delay * 2
            if self.max_retry_delay is not None:
                new_delay = min(new_delay, self.max_retry_delay)
            return new_delay
        else:
            return current_delay

    def _get_next_fallback_model(self, current_model: str) -> Optional[str]:
        if current_model in self.fallback_models:
            idx = self.fallback_models.index(current_model)
            next_idx = (idx + 1) % len(self.fallback_models)
            if next_idx == idx:
                return None
            return self.fallback_models[next_idx]
        else:
            if not self.fallback_models:
                return None
            return self.fallback_models[0]

    ############################################################################
    # ЛОГИКА ОГРАНИЧЕНИЯ ТОКЕНОВ (обрезка или суммаризация)
    ############################################################################
    def _check_and_adjust_messages(self, messages: List[Dict[str, str]]) -> List[Dict[str, str]]:
        prompt_tokens = self._count_messages_tokens(messages)

        if prompt_tokens + self.max_tokens <= self.token_limit:
            return messages

        self.logger.warning(
            "MessageExceedsTokenLimit",
            prompt_tokens=prompt_tokens,
            max_tokens=self.max_tokens,
            token_limit=self.token_limit
        )

        if self.summarize_old_messages:
            return self._summarize_excess_messages(messages)
        else:
            return self._truncate_messages(messages)

    def _summarize_excess_messages(self, messages: List[Dict[str, str]]) -> List[Dict[str, str]]:
        max_summaries = 3
        summary_round = 0
        current_messages = messages

        while summary_round < max_summaries:
            prompt_tokens = self._count_messages_tokens(
                current_messages) + self.max_tokens
            if prompt_tokens <= self.token_limit:
                break

            chunk_to_summarize = current_messages[:3]
            text_block = "\n".join(
                [f"{m['role']}:\n{m['content']}" for m in chunk_to_summarize]
            )
            summary_input = [
                {"role": "system",
                    "content": "You are a helpful AI assistant specialized in summarizing text."},
                {"role": "user", "content": f"{self.summary_prompt}\n{text_block}"}
            ]

            self.logger.debug(
                f"Summarizing old messages, round={summary_round+1}...")

            try:
                backup_key = openai.api_key
                response = openai.ChatCompletion.create(
                    model=self.model,
                    messages=summary_input,
                    max_tokens=256,
                    temperature=0.0
                )
                openai.api_key = backup_key

                summary_text = response["choices"][0]["message"]["content"]
                new_summary_msg = {
                    "role": "system",
                    "content": f"Conversation summary:\n{summary_text}"
                }
                current_messages = [new_summary_msg] + current_messages[3:]
                summary_round += 1

            except Exception as e:
                self.logger.error("SummarizationError", error=str(e))
                return self._truncate_messages(current_messages)

        return current_messages

    def _truncate_messages(self, messages: List[Dict[str, str]]) -> List[Dict[str, str]]:
        truncated = []
        total_tokens = 0
        encoding = self._get_encoding()
        limit_for_prompt = self.token_limit - self.max_tokens

        for msg in messages:
            msg_token_count = len(encoding.encode(msg["content"]))
            if total_tokens + msg_token_count <= limit_for_prompt:
                truncated.append(msg)
                total_tokens += msg_token_count
            else:
                break

        self.logger.warning("Truncated messages due to token limit.")
        return truncated

    def _count_messages_tokens(self, messages: List[Dict[str, str]]) -> int:
        encoding = self._get_encoding()
        total = 0
        for msg in messages:
            total += len(encoding.encode(msg["content"]))
        return total

    @staticmethod
    def _get_encoding():
        try:
            return tiktoken.encoding_for_model("gpt-3.5-turbo")
        except Exception:
            return tiktoken.get_encoding("cl100k_base")

    ############################################################################
    # НАСТРОЙКА МОДЕЛИ И КЛЮЧЕЙ "НА ЛЕТУ"
    ############################################################################
    def set_model(self, model: str):
        self.model = model
        self.logger.info(f"GPTService model changed to {model}")

    def add_api_key(self, key: str):
        self.api_key_pool.api_keys.append(key)
        self.logger.info("Added new OpenAI API key to pool")

    def remove_api_key(self, key: str):
        if key in self.api_key_pool.api_keys:
            self.api_key_pool.api_keys.remove(key)
            self.logger.info("Removed an OpenAI API key from pool")

    def clear_cache(self):
        if self.cache_enabled:
            self._chat_completion_cached.cache_clear()
            self.logger.info("GPTService cache cleared.")


# NEW: ================== ДОПОЛНЕННЫЕ УЛУЧШЕНИЯ ===================
# Ниже мы добавляем еще больше возможностей, ничего не убирая из вашего кода.

# NEW: Держать статистику (usage_data) о количестве вызовов, токенов, и т.д.
class GPTUsageStats:
    """
    Хранит статистику использования GPT (кол-во вызовов, суммарное время, кол-во токенов).
    """

    def __init__(self):
        self.call_count = 0
        self.total_time = 0.0
        self.total_tokens_used = 0
        self.last_call_timestamp = None

    def record_call(self, tokens_used: int, duration: float):
        self.call_count += 1
        self.total_time += duration
        self.total_tokens_used += tokens_used
        self.last_call_timestamp = datetime.now()

    def to_dict(self) -> dict:
        return {
            "call_count": self.call_count,
            "total_time": self.total_time,
            "total_tokens_used": self.total_tokens_used,
            "last_call_timestamp": self.last_call_timestamp.isoformat() if self.last_call_timestamp else None
        }


class GPTServiceEnhanced(GPTService):
    """
    Наследуемся от GPTService, не убирая ничего из оригинала, 
    а лишь расширяем логику:
    - Сбор статистики usage_data
    - Дополнительный system_prompt (опциональный)
    - Вызов custom_methods (пример)
    """

    def __init__(
        self,
        *args,
        record_usage: bool = False,  # NEW: флаг, включающий сбор статистики
        system_prompt: Optional[str] = None,  # NEW: Доп. системный промпт
        **kwargs
    ):
        super().__init__(*args, **kwargs)
        self.record_usage = record_usage
        self.system_prompt = system_prompt or ""
        self.usage_stats = GPTUsageStats() if record_usage else None

    def chat_completion(
        self,
        messages: List[Dict[str, str]],
        user_id: Optional[str] = None
    ) -> str:
        """
        Переопределяем, чтобы добавить system_prompt (если указан),
        и собирать статистику (если record_usage=True).
        """
        # Если задан system_prompt, prepend его в начало как system
        if self.system_prompt:
            # Проверяем, нет ли уже system
            first_role = messages[0]["role"] if messages else None
            if first_role == "system":
                # Просто добавим к существующему system
                messages[0]["content"] = self.system_prompt + \
                    "\n" + messages[0]["content"]
            else:
                # prepend
                messages = [
                    {"role": "system", "content": self.system_prompt}] + messages

        start_time = time.time()
        result = super().chat_completion(messages, user_id=user_id)
        duration = time.time() - start_time

        # Если нужно собирать usage
        if self.record_usage and self.usage_stats:
            # Примерно подсчитаем токены (prompt + ответ)
            token_count = self._count_messages_tokens(messages)
            # +max_tokens?
            # Для более точного подсчета,
            # можно parse(usage.total_tokens) из response, но response у нас "строка"...
            # (В _chat_completion_impl можно ловить usage_info.)

            self.usage_stats.record_call(token_count, duration)

        return result

    def get_usage_data(self) -> dict:
        """
        Возвращает текущую статистику usage (если record_usage=True).
        Если отключено — возвращаем пусто.
        """
        if self.record_usage and self.usage_stats:
            return self.usage_stats.to_dict()
        return {}

    def reset_usage_data(self):
        """ Сбрасываем накопленную статистику. """
        if self.record_usage and self.usage_stats:
            self.usage_stats = GPTUsageStats()
            self.logger.info("Usage stats reset.")


# КОНЕЦ NEW =======================================
