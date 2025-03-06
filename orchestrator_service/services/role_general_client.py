# role_general_client.py

import os
import logging
import time
import hashlib
from typing import Optional, Dict, Tuple, Any, List

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from pydantic import BaseModel, Field, ValidationError

logger = logging.getLogger(__name__)

########################################################################
# 1. Кастомные исключения
########################################################################


class RoleClientError(Exception):
    """Базовое исключение при работе с Role General Service."""
    pass


class RoleClientNetworkError(RoleClientError):
    """
    Сетевая ошибка или таймаут при обращении к Role General Service.
    Например, requests.exceptions.Timeout или ConnectionError.
    """
    pass


class RoleClientAPIError(RoleClientError):
    """
    Ошибка HTTP (4xx/5xx) или некорректный JSON от сервиса.
    """
    pass


class RoleClientRejectedContent(RoleClientError):
    """
    Сервис вернул «логическую» ошибку (например, в поле 'error'),
    говоря, что генерация черновика не удалась.
    """
    pass


########################################################################
# 2. Pydantic-модели (вход / выход)
########################################################################

class GenerateDraftRequest(BaseModel):
    """
    Данные, которые отправляем в Role General Service для генерации черновика.
    Можно добавлять любые поля (tone, keywords, etc.).
    """
    title: str = Field(...,
                       description="Название проекта/задачи или основной темы")
    language: str = Field(
        "en", description="Язык для генерации (en, ru и т. д.)")
    style: str = Field(
        "formal", description="Стиль текста (formal, casual, etc.)")
    max_length: int = Field(500, description="Максимальный размер текста")

    # Пример дополнительных полей:
    # keywords: List[str] = []
    # tone: Optional[str] = None
    # additional_context: Optional[str] = None


class GenerateDraftResponse(BaseModel):
    """
    Результат ответа от Role General Service.
    Может содержать 'error', если сервис не смог сгенерировать текст.
    """
    generated_text: str = Field(...,
                                description="Сгенерированный черновик текста")
    tokens_used: Optional[int] = Field(
        None, description="Число использованных токенов (если актуально)")
    additional_info: Optional[Dict[str, Any]] = Field(
        None, description="Прочие сведения")
    error: Optional[str] = None  # Если сервис вернёт признак отказа


########################################################################
# 3. Кэш в памяти
########################################################################

class RoleCache:
    """
    Простой кэш: (hash(GenerateDraftRequest) -> (timestamp, GenerateDraftResponse)).
    Для продакшена логичнее Redis, но логика такая же: lookup, set, TTL.
    """

    def __init__(self, ttl: int = 60):
        self.ttl_seconds = ttl
        self._storage: Dict[str, Tuple[float, GenerateDraftResponse]] = {}

    def _make_key(self, req: GenerateDraftRequest) -> str:
        # Хэшируем сериализованный req
        raw = req.json().encode("utf-8")
        return hashlib.md5(raw).hexdigest()

    def get(self, req: GenerateDraftRequest) -> Optional[GenerateDraftResponse]:
        key = self._make_key(req)
        entry = self._storage.get(key)
        if not entry:
            return None

        created_time, result = entry
        if (time.time() - created_time) > self.ttl_seconds:
            self._storage.pop(key, None)
            return None
        return result

    def set(self, req: GenerateDraftRequest, response: GenerateDraftResponse):
        key = self._make_key(req)
        self._storage[key] = (time.time(), response)


########################################################################
# 4. Основной клиент RoleGeneralClient
########################################################################

class RoleGeneralClient:
    """
    Класс для взаимодействия с Role General Service (генерация черновиков на GPT и т. п.).
    Поддерживает:
     - HTTP POST с retries
     - Таймаут
     - Кэширование (use_cache)
     - fallback_urls (если основной хост упал)
     - Кастомные исключения
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
        :param base_url: Основной URL Role Service (например, http://role_general:5001/generate-draft)
        :param fallback_urls: Список резервных URL (если основной упадёт)
        :param timeout: Таймаут (сек)
        :param retries: Количество повторных попыток (429, 5xx)
        :param use_cache: Включить кэш?
        :param cache_ttl: Сколько секунд хранить запись в кэше
        """
        self.base_url = base_url
        self.fallback_urls = fallback_urls or []
        self.timeout = timeout
        self.use_cache = use_cache
        self._cache = RoleCache(ttl=cache_ttl) if use_cache else None

        # Создаём сессию requests + retry
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
            f"RoleGeneralClient инициализирован: base_url={base_url}, fallback={self.fallback_urls}, timeout={timeout}, retries={retries}, use_cache={use_cache}")

    def generate_draft(
        self,
        request_data: GenerateDraftRequest,
        request_id: str = "no-request-id"
    ) -> GenerateDraftResponse:
        """
        Метод: отправляем POST-запрос на Role Service, возвращаем GenerateDraftResponse.
        Может бросать:
          - RoleClientNetworkError (таймаут, сетевой сбой)
          - RoleClientAPIError (4xx/5xx или кривой JSON)
          - RoleClientRejectedContent (поле "error" в ответе)
        """
        # 1. Проверяем кэш
        if self.use_cache and self._cache:
            cached = self._cache.get(request_data)
            if cached:
                logger.info(
                    f"[{request_id}] RoleClient: взяли результат из кэша (len={len(cached.generated_text)})")
                return cached

        # 2. Пробуем основной URL + fallback
        urls_to_try = [self.base_url] + self.fallback_urls
        last_exception = None

        for url in urls_to_try:
            try:
                return self._do_request(url, request_data, request_id)
            except RoleClientNetworkError as ne:
                logger.error(f"[{request_id}] Сетевая ошибка: {ne} (fallback)")
                last_exception = ne
            except RoleClientAPIError as ae:
                logger.error(f"[{request_id}] APIError: {ae} (fallback)")
                last_exception = ae
            except RoleClientRejectedContent as rc:
                # Логическая ошибка: сервис отказался (поле "error" в JSON).
                raise rc
            except Exception as e:
                logger.exception(f"[{request_id}] Неизвестная ошибка: {e}")
                last_exception = e

        error_msg = f"All RoleService URLs failed. Last error: {last_exception}"
        logger.error(f"[{request_id}] {error_msg}")
        raise RoleClientNetworkError(error_msg)

    def _do_request(
        self,
        url: str,
        request_data: GenerateDraftRequest,
        request_id: str
    ) -> GenerateDraftResponse:
        """
        Выполняет реальный запрос (POST) к Role Service, возвращает GenerateDraftResponse или бросает исключения.
        """
        payload = request_data.dict()
        logger.info(
            f"[{request_id}] RoleClient: POST {url}, payload={payload}")

        try:
            resp = self.session.post(url, json=payload, timeout=self.timeout)
        except requests.exceptions.Timeout as te:
            raise RoleClientNetworkError(f"Timeout {te}") from te
        except requests.exceptions.RequestException as re:
            raise RoleClientNetworkError(f"Network error: {re}") from re

        if not resp.ok:
            # HTTP-код != 200..299
            msg = f"RoleService returned {resp.status_code}: {resp.text}"
            if 400 <= resp.status_code < 500:
                raise RoleClientAPIError(msg)
            else:
                raise RoleClientAPIError(msg)

        # Разбор JSON
        try:
            data = resp.json()
        except ValueError as ve:
            raise RoleClientAPIError(
                f"Invalid JSON from RoleService: {ve}") from ve

        # Валидируем через Pydantic
        try:
            result = GenerateDraftResponse(**data)
        except ValidationError as vex:
            raise RoleClientAPIError(
                f"Incompatible JSON for GenerateDraftResponse: {vex}") from vex

        # Если сервис вернул "error", считаем, что генерация отклонена
        if result.error:
            raise RoleClientRejectedContent(
                f"Role Service rejected: {result.error}")

        # Успешный результат
        if self.use_cache and self._cache:
            self._cache.set(request_data, result)

        logger.info(
            f"[{request_id}] Успешно получили черновик (len={len(result.generated_text)})")
        return result


########################################################################
# 5. (Опционально) Асинхронная версия
#     Если вы перейдёте на httpx + async
########################################################################

# import httpx
# import asyncio

# class AsyncRoleGeneralClient:
#     def __init__(...):
#         ...
#     async def generate_draft_async(self, request_data: GenerateDraftRequest, request_id: str = "no-request-id"):
#         ...
#         # Вызывать httpx.AsyncClient().post(...), ловить ошибки,
#         # бросать AsyncRoleClientNetworkError, AsyncRoleClientAPIError, etc.
