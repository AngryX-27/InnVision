# translation_client.py

import os
import logging
import time
import hashlib
from typing import Optional, Dict, Any, Tuple, List

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from pydantic import BaseModel, Field, ValidationError

logger = logging.getLogger(__name__)

########################################################################
# 0. Кастомные исключения
########################################################################


class TranslationClientError(Exception):
    """Базовое исключение при работе с сервисом перевода."""
    pass


class TranslationClientBadRequest(TranslationClientError):
    """
    Ошибка 4xx (неправильный запрос) – обычно нет смысла ретраить или fallback.
    """
    pass


class TranslationClientServerError(TranslationClientError):
    """
    Ошибка 5xx (сервис упал) – можно fallback'нуть, если есть?
    """
    pass


class TranslationClientTimeout(TranslationClientError):
    """
    Таймаут при обращении к сервису перевода.
    """
    pass


class TranslationClientNetworkError(TranslationClientError):
    """
    Сетевая ошибка (DNS, подключение), отличная от таймаута и HTTP-кодов.
    """
    pass

########################################################################
# 1. Pydantic-модели (вход/выход)
########################################################################


class TranslationRequest(BaseModel):
    """
    Модель запроса на перевод одиночного текста.
    """
    text: str = Field(..., description="Текст, который нужно перевести")
    source_lang: str = Field(
        "en", description="Язык исходного текста (пример: en, ru)")
    target_lang: str = Field(
        "ru", description="Язык перевода (пример: en, ru)")
    formality: Optional[str] = Field(
        None, description="Уровень формальности (informal, formal, etc.)")
    glossary: Optional[Dict[str, str]] = Field(
        None, description="Словарь терминов (исходное -> перевод)")


class TranslationResponse(BaseModel):
    """
    Результат перевода одного текста.
    """
    translated_text: str = Field(..., description="Переведённый текст")
    original_text: Optional[str] = Field(
        None, description="Исходный текст (если сервис возвращает)")
    provider: Optional[str] = Field(
        None, description="Имя/ID провайдера (если сервис вернёт)")
    tokens_used: Optional[int] = Field(
        None, description="Число токенов, если актуально")
    additional_info: Optional[Dict[str, Any]] = Field(
        None, description="Прочие сведения о переводе")

# (Опционально) Модели для batch-перевода:


class BatchTranslationRequest(BaseModel):
    """
    Модель для пакетного перевода (список текстов).
    """
    texts: List[str] = Field(..., description="Список текстов для перевода")
    source_lang: str = Field("en", description="Исходный язык")
    target_lang: str = Field("ru", description="Целевой язык")
    formality: Optional[str] = None
    glossary: Optional[Dict[str, str]] = None


class BatchTranslationResponse(BaseModel):
    """
    Результат пакетного перевода (список).
    """
    translations: List[str] = Field(...,
                                    description="Список переведённых текстов")
    provider: Optional[str] = None
    tokens_used: Optional[int] = None
    additional_info: Optional[Dict[str, Any]] = None


########################################################################
# 2. Кэш (в памяти). Легко заменить на Redis.
########################################################################

class TranslationCache:
    """
    Простой кэш результатов перевода:
      (hash(запрос) -> (timestamp, TranslationResponse)).
    Для batch можно хранить ключ отдельно, 
    or unify (req.json() => key).
    """

    def __init__(self, ttl: int = 120):
        self.ttl_seconds = ttl
        self._storage: Dict[str, Tuple[float, Any]] = {}

    def _make_key(self, data_obj: BaseModel) -> str:
        # Универсальный ключ: сериализуем pydantic, берём md5
        raw = data_obj.json().encode("utf-8")
        return hashlib.md5(raw).hexdigest()

    def get(self, data_obj: BaseModel) -> Optional[Any]:
        key = self._make_key(data_obj)
        entry = self._storage.get(key)
        if not entry:
            return None
        created_time, result = entry
        if (time.time() - created_time) > self.ttl_seconds:
            self._storage.pop(key, None)
            return None
        return result

    def set(self, data_obj: BaseModel, result: Any):
        key = self._make_key(data_obj)
        self._storage[key] = (time.time(), result)


########################################################################
# 3. TranslationClient
#    - fallback, retries, кэш, batch, токен
########################################################################

class TranslationClient:
    """
    Клиент для сервиса перевода:
      - Основной URL + fallback URLs
      - Bearer-токен (auth_token)
      - Таймаут, retries
      - Кэш (in-memory или Redis)
      - Возможность batch-перевода
    """

    def __init__(
        self,
        base_url: Optional[str] = None,
        fallback_urls: Optional[List[str]] = None,
        timeout: Optional[int] = None,
        retries: Optional[int] = None,
        auth_token: Optional[str] = None,
        use_cache: bool = False,
        cache_ttl: int = 120
    ):
        """
        :param base_url: основной URL (http://translation_service:8006/translate) или из env
        :param fallback_urls: запасные URL (или из TRANSLATION_FALLBACK_URLS)
        :param timeout: таймаут (сек)
        :param retries: кол-во повторов (429, 5xx)
        :param auth_token: Bearer-токен для авторизации
        :param use_cache: включить ли кэш
        :param cache_ttl: время жизни записи в кэше
        """
        # 1. Загружаем из env при необходимости
        self.base_url = base_url or os.getenv(
            "TRANSLATION_BASE_URL", "http://translation_service:8006/translate")

        fallback_env = os.getenv("TRANSLATION_FALLBACK_URLS", "")
        self.fallback_urls = fallback_urls or (
            fallback_env.split(",") if fallback_env else [])

        self.timeout = timeout if timeout is not None else int(
            os.getenv("TRANSLATION_TIMEOUT", 5))
        retries_val = retries if retries is not None else int(
            os.getenv("TRANSLATION_RETRIES", 3))
        self.auth_token = auth_token or os.getenv("TRANSLATION_AUTH_TOKEN", "")

        self.use_cache = use_cache
        self._cache = TranslationCache(ttl=cache_ttl) if use_cache else None

        # 2. Настраиваем requests.Session c retry
        self.session = requests.Session()
        retry_strategy = Retry(
            total=retries_val,
            backoff_factor=0.3,
            status_forcelist=[429, 500, 502, 503, 504],
            allowed_methods=["HEAD", "GET", "OPTIONS", "POST"]
        )
        adapter = HTTPAdapter(max_retries=retry_strategy)
        self.session.mount("http://", adapter)
        self.session.mount("https://", adapter)

        logger.info(f"TranslationClient инициализирован. base_url={self.base_url}, "
                    f"fallback_urls={self.fallback_urls}, timeout={self.timeout}, retries={retries_val}, "
                    f"use_cache={use_cache}, cache_ttl={cache_ttl}")

    ####################################################################
    # Точка входа для одиночного перевода
    ####################################################################
    def translate(self, req_data: TranslationRequest, request_id: str = "no-request-id") -> TranslationResponse:
        """
        Перевод одиночного текста. 
        Сначала смотрим в кэш, потом обращаемся к base_url. Если неудача -> fallback.
        """
        if self.use_cache and self._cache:
            cached = self._cache.get(req_data)
            if cached:
                logger.info(
                    f"[{request_id}] TranslationClient: взяли перевод из кэша.")
                return cached

        # fallback
        urls_to_try = [self.base_url] + self.fallback_urls
        last_exc = None

        for url in urls_to_try:
            logger.info(
                f"[{request_id}] TranslationClient: пробуем URL={url} для перевода.")
            try:
                result = self._do_single_request(req_data, url, request_id)
                if self.use_cache and self._cache:
                    self._cache.set(req_data, result)
                return result

            except TranslationClientBadRequest as br:
                # 4xx – нет смысла fallback, это наш косяк (неправильный запрос)
                raise br

            except (TranslationClientServerError, TranslationClientTimeout, TranslationClientNetworkError) as ex:
                # 5xx или таймаут – попробуем fallback
                logger.error(
                    f"[{request_id}] Ошибка при переводе через {url}: {ex} (пробуем fallback...)")
                last_exc = ex
            except Exception as e:
                logger.exception(
                    f"[{request_id}] Неизвестная ошибка при переводе: {e}")
                last_exc = e

        # Если все URL не сработали
        error_msg = f"[{request_id}] All translation providers failed. Last error: {last_exc}"
        logger.error(error_msg)
        raise TranslationClientError(error_msg)

    ####################################################################
    # Опциональный метод batch-перевода
    ####################################################################
    def translate_batch(self, batch_req: BatchTranslationRequest, request_id: str = "no-request-id") -> BatchTranslationResponse:
        """
        Перевод нескольких текстов за один запрос (если сервис это поддерживает).
        """
        if self.use_cache and self._cache:
            cached = self._cache.get(batch_req)
            if cached:
                # Предположим, вы тоже храните BatchTranslationResponse в кэше
                logger.info(
                    f"[{request_id}] TranslationClient: batch – взяли перевод из кэша.")
                return cached

        urls_to_try = [self.base_url] + self.fallback_urls
        last_exc = None

        for url in urls_to_try:
            logger.info(
                f"[{request_id}] TranslationClient: batch перевод, URL={url}.")
            try:
                result = self._do_batch_request(batch_req, url, request_id)
                if self.use_cache and self._cache:
                    self._cache.set(batch_req, result)
                return result

            except TranslationClientBadRequest as br:
                raise br  # 4xx – fallback не спасёт
            except (TranslationClientServerError, TranslationClientTimeout, TranslationClientNetworkError) as ex:
                logger.error(
                    f"[{request_id}] Ошибка batch-перевода: {ex} (fallback?)")
                last_exc = ex
            except Exception as e:
                logger.exception(
                    f"[{request_id}] Неизвестная batch-ошибка: {e}")
                last_exc = e

        raise TranslationClientError(
            f"[{request_id}] All batch translation providers failed, last error: {last_exc}")

    ####################################################################
    # Методы, которые реально делают запрос (одиночный / batch)
    ####################################################################
    def _do_single_request(self, req_data: TranslationRequest, url: str, request_id: str) -> TranslationResponse:
        payload = {
            "text": req_data.text,
            "source_lang": req_data.source_lang,
            "target_lang": req_data.target_lang,
            "formality": req_data.formality,
            "glossary": req_data.glossary
        }
        return self._send_http_request(url, payload, request_id, single=True)

    def _do_batch_request(self, batch_req: BatchTranslationRequest, url: str, request_id: str) -> BatchTranslationResponse:
        payload = {
            "texts": batch_req.texts,
            "source_lang": batch_req.source_lang,
            "target_lang": batch_req.target_lang,
            "formality": batch_req.formality,
            "glossary": batch_req.glossary
        }
        return self._send_http_request(url, payload, request_id, single=False)

    def _send_http_request(self, url: str, payload: Dict[str, Any], request_id: str, single: bool):
        """
        Универсальный метод, который отправляет POST; 
        single=True => вернёт TranslationResponse
        single=False => вернёт BatchTranslationResponse
        """
        headers = self._make_headers()
        logger.info(
            f"[{request_id}] POST {url}, payload={payload}, headers={headers}, single={single}")

        try:
            resp = self.session.post(
                url, json=payload, headers=headers, timeout=self.timeout)
        except requests.exceptions.Timeout as te:
            raise TranslationClientTimeout(f"Timeout: {te}") from te
        except requests.exceptions.RequestException as re:
            raise TranslationClientNetworkError(f"Network error: {re}") from re

        if not resp.ok:
            msg = f"TranslationService {resp.status_code}: {resp.text}"
            logger.error(f"[{request_id}] {msg}")
            if 400 <= resp.status_code < 500:
                # Неправильный запрос => BadRequest
                raise TranslationClientBadRequest(msg)
            else:
                # 5xx => ServerError
                raise TranslationClientServerError(msg)

        # Пробуем JSON
        try:
            data = resp.json()
        except ValueError as ve:
            raise TranslationClientServerError(f"Invalid JSON: {ve}") from ve

        # Валидируем через pydantic
        try:
            if single:
                result = TranslationResponse(**data)
            else:
                result = BatchTranslationResponse(**data)
        except ValidationError as vex:
            raise TranslationClientServerError(
                f"Response validation error: {vex}") from vex

        # Если провайдер не указан, можно прописать URL
        if single and isinstance(result, TranslationResponse):
            if not result.provider:
                result.provider = url
            logger.info(
                f"[{request_id}] Успешный перевод: {len(result.translated_text)} symbols, from {req_id_substr(payload.get('source_lang'))} to {payload.get('target_lang')}")

        if not single and isinstance(result, BatchTranslationResponse):
            if not result.provider:
                result.provider = url
            logger.info(
                f"[{request_id}] Успешный batch-перевод: {len(result.translations)} items")

        return result

    def _make_headers(self) -> Dict[str, str]:
        """
        Подготавливаем заголовки (Bearer токен), если есть.
        """
        headers = {}
        if self.auth_token:
            headers["Authorization"] = f"Bearer {self.auth_token}"
        return headers


def req_id_substr(lang):
    # Пример небольшой вспомогательной функции
    return lang if lang else "?"

########################################################################
# 4. (Опционально) Асинхронная реализация (закомментировано)
########################################################################

# import httpx
# import asyncio
#
# class AsyncTranslationClient:
#     def __init__(..., use_cache: bool=False, cache_ttl: int=120):
#         # Аналогично, но httpx.AsyncClient + asyncio
#         ...
#
#     async def translate(self, req_data: TranslationRequest, request_id="no-request"):
#         ...
#
#     async def translate_batch(self, batch_req: BatchTranslationRequest, request_id="no-request"):
#         ...
#
#     # _send_http_request_async(...) — аналог.
