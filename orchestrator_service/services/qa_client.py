# qa_client.py

import os
import logging
import time
import hashlib
from typing import Optional, Any, Dict, List

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from pydantic import BaseModel, Field, ValidationError

logger = logging.getLogger(__name__)


# ======================================================
# 1. Пользовательские исключения для QAClient
# ======================================================
class QAClientError(Exception):
    """Общее исключение при работе с QA-сервисом."""
    pass


class QAClientNetworkError(QAClientError):
    """Сетевая ошибка при обращении к QA-сервису (таймаут, conn error)."""
    pass


class QAClientAPIError(QAClientError):
    """QA-сервис ответил кодом 4xx/5xx или некорректным JSON."""
    pass


class QAClientRejectedContent(QAClientError):
    """QA-сервис вернул бизнес-ошибку (например, текст не прошёл проверку)."""
    pass


# ======================================================
# 2. Модели для входных/выходных данных
# ======================================================
class CheckContentRequest(BaseModel):
    """
    Входные данные, которые передаются в QA-сервис.
    Можно дополнять полями для стиля, терминологии и т.д.
    """
    text: str = Field(..., description="Текст, который нужно проверить")
    language: str = Field("en", description="Язык текста (en, ru и т.д.)")
    check_spelling: bool = Field(True, description="Проверять орфографию?")
    check_profanity: bool = Field(
        True, description="Проверять запрещённые слова?")
    # Доп. поля: check_style, check_terminology, etc.


class QaCheckResult(BaseModel):
    """
    Результат проверки QA.
      - checked_text: итоговый (возможно, исправленный) текст
      - typos_detected: число орфографических ошибок
      - profanity_found: список запрещённой лексики
      - error: опциональное поле, если QA не смог обработать текст
    """
    checked_text: str = Field(...)
    typos_detected: int = Field(0)
    profanity_found: List[str] = Field(default_factory=list)
    error: Optional[str] = None


# ======================================================
# 3. (Опционально) Кэширование
# ======================================================
class QACache:
    """
    Словарный кэш: (hash(запроса) -> (timestamp, QaCheckResult)).
    Для продакшена лучше Redis / Memcached,
    но идея та же — lookup, set, TTL.
    """

    def __init__(self, ttl_seconds: int = 60):
        self.ttl = ttl_seconds
        self._storage: Dict[str, (float, QaCheckResult)] = {}

    def _make_key(self, request: CheckContentRequest) -> str:
        # Хэшируем сериализованный request
        raw = request.json().encode("utf-8")
        return hashlib.md5(raw).hexdigest()

    def get(self, request: CheckContentRequest) -> Optional[QaCheckResult]:
        key = self._make_key(request)
        entry = self._storage.get(key)
        if not entry:
            return None

        created_time, result = entry
        if (time.time() - created_time) > self.ttl:
            self._storage.pop(key, None)
            return None
        return result

    def set(self, request: CheckContentRequest, result: QaCheckResult):
        key = self._make_key(request)
        self._storage[key] = (time.time(), result)


# ======================================================
# 4. QAClient
# ======================================================
class QAClient:
    """
    Клиент для QA-сервиса:
      - Подключение через HTTP (requests), c retries/timeout
      - Возвращает Pydantic-модель QaCheckResult
      - Может бросать исключения QAClientNetworkError, QAClientAPIError, и т.д.
      - Опциональное кэширование
      - Поддержка fallback URLs, если основной сервис недоступен
    """

    def __init__(
        self,
        base_url: str,
        fallback_urls: Optional[List[str]] = None,
        timeout: int = 5,
        retries: int = 3,
        use_cache: bool = False,
        cache_ttl: int = 60
    ):
        """
        :param base_url: Основной URL QA-сервиса, например "http://qa_service:8080/check"
        :param fallback_urls: Список резервных URL (если основной недоступен).
        :param timeout: Таймаут (сек), чтобы не виснуть бесконечно.
        :param retries: Число повторов при статусах 429, 500, 502, 503, 504.
        :param use_cache: Включает ли кэш результатов.
        :param cache_ttl: Время жизни кэша (сек).
        """
        self.base_url = base_url
        self.fallback_urls = fallback_urls or []
        self.timeout = timeout
        self.use_cache = use_cache
        self._cache = QACache(ttl_seconds=cache_ttl) if use_cache else None

        # requests.Session c retry
        self.session = requests.Session()
        retry_strategy = Retry(
            total=retries,
            backoff_factor=0.3,
            status_forcelist=[429, 500, 502, 503, 504],
            allowed_methods=["HEAD", "GET", "OPTIONS", "POST"]
        )
        adapter = HTTPAdapter(max_retries=retry_strategy)
        self.session.mount("http://", adapter)
        self.session.mount("https://", adapter)

        logger.info(
            f"QAClient инициализирован. base_url={base_url}, fallback={self.fallback_urls}, timeout={timeout}, retries={retries}, use_cache={use_cache}.")

    def check_content(
        self,
        request_data: CheckContentRequest,
        request_id: str = "unknown-request"
    ) -> QaCheckResult:
        """
        Отправляет POST на QA-сервис (или fallback), возвращает QaCheckResult.
        Бросает исключения QAClientNetworkError, QAClientAPIError, QAClientRejectedContent.
        """
        if self.use_cache and self._cache:
            cached = self._cache.get(request_data)
            if cached:
                logger.info(
                    f"[{request_id}] QAClient: результат взят из кэша.")
                return cached

        # Список URL: основной + fallback
        urls_to_try = [self.base_url] + self.fallback_urls
        last_exception: Optional[Exception] = None

        for url in urls_to_try:
            logger.info(
                f"[{request_id}] QAClient: пробуем URL={url} для проверки контента.")
            try:
                return self._do_request(url, request_data, request_id)
            except QAClientNetworkError as ne:
                logger.error(
                    f"[{request_id}] Сетевая ошибка при запросе к {url}: {ne} (пробуем fallback...)")
                last_exception = ne
            except QAClientAPIError as ae:
                # Если вернулся 4xx/5xx или некорректный JSON, считаем, что fallback не поможет?
                # Или можно продолжить?
                logger.error(
                    f"[{request_id}] APIError при запросе к {url}: {ae} (пробуем fallback...)")
                last_exception = ae
            except QAClientRejectedContent as rc:
                # Бизнес-ошибка: QA отклонил текст
                # Смысла fallback нет, т.к. сама проверка не прошла
                raise rc
            except Exception as e:
                logger.exception(
                    f"[{request_id}] Неизвестная ошибка при обращении к {url}")
                last_exception = e

        # Если все URL упали
        error_msg = f"All QA providers failed. Last error: {str(last_exception)}"
        logger.error(f"[{request_id}] {error_msg}")
        raise QAClientNetworkError(error_msg)

    def _do_request(
        self,
        url: str,
        request_data: CheckContentRequest,
        request_id: str
    ) -> QaCheckResult:
        """
        Выполняет реальный POST на заданный URL, возвращает QaCheckResult или бросает исключения.
        """
        payload = {
            "text": request_data.text,
            "language": request_data.language,
            "spellcheck": request_data.check_spelling,
            "profanity": request_data.check_profanity
        }
        logger.info(f"[{request_id}] QAClient: POST {url}, payload={payload}")

        try:
            resp = self.session.post(url, json=payload, timeout=self.timeout)
        except requests.exceptions.Timeout as te:
            raise QAClientNetworkError(f"Timeout: {te}") from te
        except requests.exceptions.RequestException as re:
            raise QAClientNetworkError(f"Network error: {re}") from re

        if not resp.ok:
            # HTTP-код не 2xx (4xx/5xx)
            msg = f"QAService responded with {resp.status_code} {resp.text}"
            if 400 <= resp.status_code < 500:
                # Считаем это "бизнес-ошибкой" или некорректным запросом
                # Можно бросать QAClientRejectedContent, если сервис указывает,
                # что контент неприемлем. Или QAClientAPIError
                raise QAClientAPIError(msg)
            else:
                # 5xx
                raise QAClientAPIError(msg)

        try:
            data = resp.json()
        except ValueError as ve:
            raise QAClientAPIError(
                f"Invalid JSON from QAService: {ve}") from ve

        # Валидируем через pydantic
        try:
            result = QaCheckResult(**data)
        except ValidationError as vex:
            raise QAClientAPIError(
                f"QAService returned incompatible JSON: {vex}") from vex

        if result.error:
            # Если QA-сервис вернул "error" в теле
            raise QAClientRejectedContent(
                f"QA rejected content: {result.error}")

        # Успешный результат
        if self.use_cache and self._cache:
            self._cache.set(request_data, result)

        logger.info(
            f"[{request_id}] Успешная проверка QA, typos_detected={result.typos_detected}, profanity_found={result.profanity_found}")
        return result


########################################################################
# 5. (Опционально) Пример асинхронной версии (закомментировано)
#    Если перейдёте на asyncio + httpx
########################################################################

# import httpx
# import asyncio

# class AsyncQAClient:
#     def __init__(self, base_url: str, fallback_urls: Optional[List[str]] = None, ...):
#         ...

#     async def check_content_async(self, request_data: CheckContentRequest, request_id: str="unknown-request") -> QaCheckResult:
#         # Аналогично _do_request, но через httpx.AsyncClient
#         async with httpx.AsyncClient(...) as client:
#             try:
#                 resp = await client.post(url, json=payload, timeout=self.timeout)
#                 ...
#             except httpx.TimeoutException:
#                 raise QAClientNetworkError("Timeout ...")
#             ...
#         ...
