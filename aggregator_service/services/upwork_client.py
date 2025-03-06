"""
upwork_client.py

Боевой пример клиента для работы с UpWork API:
 - Использует OAuth2 (client credentials или refresh token flow), 
   обрабатывая сроки действия токена, автоперезапрашивая при истечении.
 - Применяет requests.Session + requests_oauthlib для HTTP-запросов и обновления токена.
 - Включает систему ретраев (tenacity) при временных ошибках/5xx/429 rate limit.
 - Структурное логгирование (structlog).
 - Кастомные исключения UpWorkClientError / UpWorkServerError / UpWorkRateLimitError.
 - Методы fetch_jobs, create_proposal, get_proposal_status, get_job_details, accept_invitation...
 - Дополнительно: handle_new_job(...) и handle_additional_info(...), чтобы создавать/обновлять TЗ (через tz_storage_db).
   Это позволяет боту автоматически формировать JSONB-документ TЗ в БД, не перемешивая с другими таблицами.

Прежде чем использовать, убедитесь, что у вас есть:
 - UpWork "client_id" и "client_secret"
 - Зарегистрированное приложение на стороне UpWork (Developer center)
 - Правильная конфигурация endpoint'ов (base_url, token_url, пр.)

Подготовлено на Python 3.9+, требует:
 pip install requests requests-oauthlib structlog tenacity
"""

import os
import json
import logging
from typing import List, Dict, Any, Optional, Union
import time  # NEW: используем для измерения времени вызовов, если хотим

import structlog
import requests
from requests import Response
from requests_oauthlib import OAuth2Session
from oauthlib.oauth2 import BackendApplicationClient, TokenExpiredError
from tenacity import (
    retry,
    stop_after_attempt,
    wait_exponential,
    retry_if_exception_type
)
from requests.exceptions import RequestException, HTTPError

# ==============  NEW IMPORTS FOR TЗ storage and analysis ================
from aggregator_service.db import SessionLocal
from aggregator_service.logic.tz_storage_db import create_tz, update_tz
from aggregator_service.logic.analyze import analyze_request
# ========================================================================

###############################################################################
# Структурное логгирование (примерная настройка)
###############################################################################
structlog.configure(
    processors=[
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.dev.ConsoleRenderer()
    ],
    wrapper_class=structlog.make_filtering_bound_logger(min_level="INFO"),
    context_class=dict,
    cache_logger_on_first_use=True,
)
logger = structlog.get_logger(__name__)

###############################################################################
# Пользовательские исключения
###############################################################################


class UpWorkError(Exception):
    """Базовое исключение для любых проблем с UpWork API."""


class UpWorkClientError(UpWorkError):
    """Ошибки 4xx (клиентские) при запросах к UpWork."""


class UpWorkServerError(UpWorkError):
    """Ошибки 5xx (сервер UpWork) при запросах."""


class UpWorkRateLimitError(UpWorkError):
    """Rate limit, 429 от UpWork."""


###############################################################################
# UpWorkClient: боевой пример с OAuth2 (Client Credentials / Refresh Token flow)
###############################################################################
class UpWorkClient:
    """
    Клиент для работы с UpWork API в продакшен-сценариях:
      - OAuth2 аутентификация/авторизация (через requests_oauthlib).
      - Автоматическое обновление токена (refresh_token), если поддерживается.
      - Ретраи (tenacity) при сетевых/временных ошибках (429, 5xx).
      - Методы: fetch_jobs, create_proposal, get_proposal_status, get_job_details, accept_invitation.
      - handle_new_job(...), handle_additional_info(...) для создания/обновления TЗ (tz_storage_db).

    Пример использования:
        client = UpWorkClient(base_url="...", token_url="...", client_id="...", client_secret="...")
        jobs = client.fetch_jobs(category="Writing", limit=2)
        if jobs:
            client.handle_new_job(jobs[0])
    """

    def __init__(
        self,
        base_url: str,
        token_url: str,
        client_id: str,
        client_secret: str,
        scope: Optional[List[str]] = None,
        logger: Union[logging.Logger,
                      structlog.stdlib.BoundLogger, None] = None,
        timeout: int = 10,
        max_retries: int = 3,
        backoff_multiplier: float = 2.0,
        session: Optional[requests.Session] = None,
        existing_token: Optional[Dict[str, Any]] = None
    ):
        """
        :param base_url: e.g. "https://www.upwork.com/api/v3"
        :param token_url: e.g. "https://www.upwork.com/api/v3/oauth2/token"
        :param client_id: Ваш UpWork client_id
        :param client_secret: Ваш UpWork client_secret
        :param scope: Список scope (["basic", "proposal"] и т.д.)
        :param logger: Объект логгера (structlog), если не указан — создаётся локальный.
        :param timeout: Таймаут на HTTP-запросы (сек).
        :param max_retries: Макс. число повторов при ошибках (RateLimit/5xx).
        :param backoff_multiplier: Коэффициент экспоненциального бэкоффа.
        :param session: Ваш requests.Session (если хотите переопределить).
        :param existing_token: уже существующий токен (access_token, refresh_token).
        """
        self.base_url = base_url.rstrip("/")
        self.token_url = token_url
        self.client_id = client_id
        self.client_secret = client_secret
        self.scope = scope or ["basic"]
        self.timeout = timeout
        self.max_retries = max_retries
        self.backoff_multiplier = backoff_multiplier

        if logger is not None:
            self.logger = logger
        else:
            self.logger = structlog.get_logger("UpWorkClient")

        if session is None:
            session = requests.Session()
        self.session = session

        client = BackendApplicationClient(
            client_id=self.client_id, scope=self.scope)
        self.oauth = OAuth2Session(client=client)

        if existing_token:
            self.logger.info("Using existing token from storage.")
            self.oauth.token = existing_token
        else:
            self.logger.info(
                "No existing token, fetching new one via client credentials.")
            self._fetch_token()

        self._update_auth_header()

        self.logger.info(
            "UpWorkClient initialized",
            base_url=self.base_url,
            token_url=self.token_url,
            scopes=self.scope
        )

    def _fetch_token(self):
        """
        Получаем новый access token (Client Credentials flow).
        """
        try:
            token_data = self.oauth.fetch_token(
                token_url=self.token_url,
                client_id=self.client_id,
                client_secret=self.client_secret,
                scope=self.scope
            )
            self.logger.info("Fetched new token",
                             token_type=token_data.get("token_type"))
        except Exception as e:
            self.logger.error("Failed to fetch token", error=str(e))
            raise UpWorkError(f"Cannot obtain token: {str(e)}")

    def _update_auth_header(self):
        """
        Обновляет заголовок Authorization: Bearer <token> в self.session,
        чтобы все дальнейшие запросы имели правильный токен.
        """
        access_token = self.oauth.token.get("access_token")
        if not access_token:
            raise UpWorkError("No access_token found in OAuth2Session.")

        short_token = access_token[:4] + "..." + access_token[-4:]
        self.logger.debug("Using access_token", masked=short_token)

        self.session.headers.update({
            "Authorization": f"Bearer {access_token}"
        })

    def _ensure_token_valid(self):
        """
        Проверяем, не истёк ли токен.
        Если UpWork не поддерживает refresh_token, заново получаем токен.
        """
        try:
            self.oauth.token_updater = self._token_saver
            # сделаем фиктивный GET, если TokenExpiredError — библиотека сама бросит
            self.oauth.get("https://www.example.com/check-expire", timeout=1)
        except TokenExpiredError:
            self.logger.info("TokenExpiredError - refetching token.")
            self._fetch_token()
            self._update_auth_header()

    def _token_saver(self, token_data: Dict[str, Any]):
        """
        Если библиотека обновит токен, мы сохраняем его,
        затем вызов _update_auth_header() для подстановки нового токена.
        """
        self.logger.info("Token saver called",
                         new_access_token=token_data.get("access_token"))
        self.oauth.token = token_data
        self._update_auth_header()

    @retry(
        reraise=True,
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=10),
        retry=retry_if_exception_type(
            (RequestException, UpWorkRateLimitError, UpWorkServerError)
        )
    )
    def _request(self, method: str, endpoint: str, **kwargs) -> Dict[str, Any]:
        """
        Универсальный метод HTTP-запроса с ретраями,
        проверкой токена и обработкой ошибок.

        :param method: GET/POST/PUT/PATCH/DELETE
        :param endpoint: может быть абсолютным URL либо относительным, которое мы сочетаем c base_url
        :param kwargs: параметры запроса (json, params, headers, etc.)
        :return: dict (JSON-ответ)
        """
        self._ensure_token_valid()

        url = endpoint if endpoint.startswith(
            "http") else f"{self.base_url.rstrip('/')}/{endpoint.lstrip('/')}"
        kwargs.setdefault("timeout", self.timeout)

        method_upper = method.upper()
        self.logger.debug("UpWork request start",
                          method=method_upper, url=url, **kwargs)
        try:
            resp: Response = self.session.request(method_upper, url, **kwargs)
        except RequestException as re:
            self.logger.error("Network error on request",
                              error=str(re), url=url)
            raise re

        status_code = resp.status_code

        if status_code == 429:
            raise UpWorkRateLimitError("Rate limit (429) from UpWork.")

        if 400 <= status_code < 500:
            try:
                error_data = resp.json()
                error_msg = error_data.get("error_description", resp.text)
            except Exception:
                error_msg = resp.text
            raise UpWorkClientError(f"UpWork 4xx: {status_code}, {error_msg}")

        if 500 <= status_code < 600:
            try:
                error_data = resp.json()
                error_msg = error_data.get("error_description", resp.text)
            except Exception:
                error_msg = resp.text
            raise UpWorkServerError(f"UpWork 5xx: {status_code}, {error_msg}")

        try:
            data = resp.json()
        except json.JSONDecodeError:
            self.logger.warning("Non-JSON response", text=resp.text)
            return {}

        self.logger.debug("UpWork request success", status_code=status_code)
        return data

    ###########################################################################
    # Публичные методы (fetch_jobs, create_proposal, ...)
    ###########################################################################
    def fetch_jobs(self, category: str = "Writing", limit: int = 10) -> List[Dict[str, Any]]:
        """
        Получаем список Job'ов (заказов) с UpWork (пример).
        :param category: Категория (напр. "Writing", "Translation")
        :param limit: Сколько взять (параметр paging).
        :return: список job-словарей
        """
        endpoint = "/jobs/search"
        params = {
            "category2": category,
            "paging": f"0;{limit}"
        }
        data = self._request("GET", endpoint, params=params)
        jobs = data.get("jobs", [])
        self.logger.info("Fetched jobs", category=category, count=len(jobs))
        return jobs

    def create_proposal(self, proposal_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Создаём proposal (заявку) на заказ.
        :param proposal_data: dict {"job_id":"...", "cover_letter":"...", "charge_rate":...}
        :return: JSON-ответ API UpWork
        """
        endpoint = "/proposals"
        resp = self._request("POST", endpoint, json=proposal_data)
        self.logger.info("Created proposal",
                         proposal_id=resp.get("proposal_id"))
        return resp

    def get_proposal_status(self, proposal_id: str) -> Dict[str, Any]:
        """
        Запрос статуса proposal по ID.
        """
        endpoint = f"/proposals/{proposal_id}/status"
        resp = self._request("GET", endpoint)
        self.logger.info("Proposal status",
                         proposal_id=proposal_id, status=resp.get("status"))
        return resp

    def get_job_details(self, job_id: str) -> Dict[str, Any]:
        """
        Получение подробностей конкретного job (включая описание, budget).
        """
        endpoint = f"/jobs/{job_id}"
        resp = self._request("GET", endpoint)
        self.logger.debug("Job details", job_id=job_id, details=resp)
        return resp

    def accept_invitation(self, invitation_id: str) -> Dict[str, Any]:
        """
        Пример: принимаем приглашение на проект.
        """
        endpoint = f"/invitations/{invitation_id}/accept"
        resp = self._request("POST", endpoint)
        self.logger.info("Invitation accepted", invitation_id=invitation_id)
        return resp

    def get_current_token(self) -> Dict[str, Any]:
        """
        Возвращает текущий dict токена (access_token, refresh_token, expires_at...).
        """
        return self.oauth.token

    def restore_token(self, token_data: Dict[str, Any]):
        """
        Восстанавливает токен из внешнего источника (если перезапуск приложения).
        """
        self.logger.info("Restoring token from external data.")
        self.oauth.token = token_data
        self._update_auth_header()

    ###########################################################################
    # Дополнения: handle_new_job и handle_additional_info для TЗ
    ###########################################################################
    def handle_new_job(self, job_data: Dict[str, Any]) -> None:
        """
        Обработка нового job, анализ (service_type, languages), 
        создание TЗ-документа в tz_storage_db, и (опционально) auto-proposal.

        :param job_data: пример {"job_id":"...", "title":"...", "description":"...", "budget":...}
        """
        job_id = job_data.get("job_id")
        title = job_data.get("title", "")
        description = job_data.get("description", "")

        # Анализируем (например, aggregator_service/logic/analyze.py)
        analysis = analyze_request(title, description)
        service_type = analysis.get("service_type")
        langs = analysis.get("languages", [])

        if not service_type:
            self.logger.info(
                "Job %s doesn't match known services. Skipping.", job_id)
            return

        order_id = f"upwork_{job_id}" if job_id else f"upwork_temp_{int(time.time())}"

        # Формируем initial_data для TЗ
        initial_data = {
            "status": "draft",
            "service_type": service_type,
            "languages": langs,
            "budget": job_data.get("budget", 0),
            "client_updates": [
                {
                    "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                    "source": "upwork",
                    "title": title,
                    "description": description
                }
            ]
        }

        with SessionLocal() as session:
            from aggregator_service.logic.tz_storage_db import create_tz
            try:
                doc = create_tz(session, order_id, initial_data)
                self.logger.info(
                    "Created TЗ for upwork job_id=%s => order_id=%s", job_id, order_id)

                # (Опционально) Можно сразу отправить пропозал (закомментировано)
                # proposal_data = {
                #   "job_id": job_id,
                #   "cover_letter": "Hello, I'd be happy to help you with your project...",
                #   "charge_rate": initial_data["budget"] or 25.0
                # }
                # proposal_resp = self.create_proposal(proposal_data)
                # self.logger.info("Proposal sent", proposal_resp=proposal_resp)

            except Exception as e:
                self.logger.error(
                    "Error creating TЗ for upwork job_id=%s: %s", job_id, e)

    def handle_additional_info(self, job_id: str, message: str) -> None:
        """
        Пример метода: если в ходе общения с клиентом на UpWork 
        получаем дополнительные детали, дополняем TЗ.
        :param job_id: ID job
        :param message: Текст от клиента (новая информация)
        """
        self.logger.info(
            "Handling additional info for job_id=%s, message=%r", job_id, message)

        with SessionLocal() as session:
            from aggregator_service.logic.tz_storage_db import update_tz
            order_id = f"upwork_{job_id}"

            updates = {
                "client_updates": [
                    {
                        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                        "source": "upwork",
                        "message": message
                    }
                ]
            }
            try:
                update_tz(session, order_id, updates)
                self.logger.info(
                    "Updated TЗ with additional info, order_id=%s", order_id)
            except Exception as e:
                self.logger.warning(
                    "Could not update TЗ for order_id=%s: %s", order_id, e)

    def handle_pdf_attachments(self, job_data: Dict[str, Any], order_id: str):
        """
        Пример: ищем PDF-файлы в job_data['attachments'],
        скачиваем, извлекаем текст через extract_text_from_pdf, 
        и обновляем TЗ (tz_storage_db) 'pdf_content' или 'client_updates'.

        :param job_data: dict с информацией о заказе (включая attachments).
        :param order_id: уже созданный order_id в tz_storage_db
        """
        attachments = job_data.get("attachments", [])
        if not attachments:
            self.logger.info(
                f"No attachments for job_id={job_data.get('job_id')}")
            return

        self.logger.info(
            f"Checking PDF attachments for job_id={job_data.get('job_id')} ...")
        with SessionLocal() as session:
            from aggregator_service.logic.tz_storage_db import update_tz

            for att in attachments:
                file_type = att.get("file_type", "").lower()   # e.g. "pdf"
                # где хранится файл
                file_url = att.get("url")
                file_name = att.get("file_name", "attachment.pdf")

                if file_type == "pdf":
                    # 1) Скачиваем PDF
                    pdf_path = self._download_pdf(file_url, file_name)
                    if not pdf_path:
                        self.logger.warning(
                            "Could not download PDF from %s", file_url)
                        continue

                    # 2) Извлекаем текст
                    pdf_text = extract_text_from_pdf(pdf_path)
                    # 3) Сохраняем в tz_storage_db
                    updates = {
                        "pdf_content": [
                            {
                                "file_name": file_name,
                                "url": file_url,
                                # например, храним только 2000 символов
                                "extracted_text": pdf_text[:2000]
                            }
                        ]
                    }
                    try:
                        update_tz(session, order_id, updates)
                        self.logger.info(
                            f"PDF extracted & updated TЗ for order_id={order_id}, file={file_name}")
                    except Exception as e:
                        self.logger.warning(
                            "Could not update TЗ with PDF content: %s", e)
                else:
                    self.logger.debug(
                        f"Skipping non-PDF attachment: {file_type} - {file_name}")

    def _download_pdf(self, file_url: str, file_name: str) -> Optional[str]:
        """
        Пример функции: скачивает PDF по file_url, сохраняет 
        локально (/tmp или aggregator_service/tmp/) 
        Возвращает локальный путь или None, если ошибка.
        """
        import tempfile
        import requests

        if not file_url.startswith("http"):
            self.logger.warning(f"Invalid file_url={file_url}")
            return None

        try:
            resp = requests.get(file_url, timeout=15)
            resp.raise_for_status()

            tmp_dir = tempfile.gettempdir()
            pdf_path = os.path.join(tmp_dir, file_name)
            with open(pdf_path, "wb") as f:
                f.write(resp.content)

            self.logger.info(f"Downloaded PDF => {pdf_path}")
            return pdf_path
        except Exception as e:
            self.logger.error(f"Error downloading PDF from {file_url}: {e}")
            return None

###############################################################################
# NEW: Расширенная версия (UpWorkClientEnhanced)
###############################################################################


class UpWorkUsageStats:
    """
    NEW: класс для хранения статистики, сколько раз вызывали методы, 
    сколько времени занимало, и т.д.
    """

    def __init__(self):
        self.call_count = 0
        self.total_time = 0.0
        self.last_call_timestamp = None

    def record_call(self, duration: float):
        self.call_count += 1
        self.total_time += duration
        self.last_call_timestamp = time.strftime("%Y-%m-%dT%H:%M:%SZ")

    def to_dict(self) -> Dict[str, Any]:
        return {
            "call_count": self.call_count,
            "total_time": self.total_time,
            "last_call_timestamp": self.last_call_timestamp
        }


class UpWorkClientEnhanced(UpWorkClient):
    """
    NEW: Наследуемся от UpWorkClient, ничего не убирая, но добавляя:
      - handle_invite / decline_invite
      - статистику usage (UpWorkUsageStats)
      - объединённый метод fetch_and_handle_jobs_enhanced
      - (optionally) можно вызвать create_proposal автоматически
    """

    def __init__(self, *args, record_usage: bool = False, **kwargs):
        super().__init__(*args, **kwargs)
        self.record_usage = record_usage
        self.usage_stats = UpWorkUsageStats() if record_usage else None

    def handle_invite(self, invitation_id: str):
        """
        Принимаем инвайт (похоже на accept_invitation), 
        но, например, хотим ещё что-то делать.
        """
        self.logger.info("Handling invite, invitation_id=%s", invitation_id)
        start_time = time.time()
        resp = self.accept_invitation(invitation_id)
        duration = time.time() - start_time

        if self.record_usage and self.usage_stats:
            self.usage_stats.record_call(duration)

        self.logger.info("Invite handled, response=%s", resp)
        return resp

    def decline_invite(self, invitation_id: str) -> Dict[str, Any]:
        """
        Пример: отклоняем приглашение (если API позволяет).
        """
        self.logger.info("Declining invite, invitation_id=%s", invitation_id)
        start_time = time.time()
        # Предположим, есть эндпоинт /invitations/{id}/decline
        endpoint = f"/invitations/{invitation_id}/decline"
        resp = self._request("POST", endpoint)
        duration = time.time() - start_time

        if self.record_usage and self.usage_stats:
            self.usage_stats.record_call(duration)

        self.logger.info("Invitation declined", invitation_id=invitation_id)
        return resp

    def fetch_and_handle_jobs_enhanced(self, category: str = "Writing", limit: int = 5):
        """
        NEW: Пример метода, который за один вызов:
          - fetch_jobs(category, limit)
          - для каждого job вызывает handle_new_job(...)
          - собирает результат.
        """
        self.logger.info(
            "Fetching and handling UpWork jobs (enhanced). category=%s, limit=%d", category, limit)
        start_time = time.time()
        jobs = self.fetch_jobs(category, limit)
        for job in jobs:
            self.handle_new_job(job)
        duration = time.time() - start_time

        if self.record_usage and self.usage_stats:
            self.usage_stats.record_call(duration)

        self.logger.info("fetch_and_handle_jobs_enhanced done",
                         job_count=len(jobs))

    def get_usage_data(self) -> Dict[str, Any]:
        """
        Возвращает статистику usage (сколько раз вызывали методы, суммарное время, ...).
        Если record_usage=False, вернём пустой dict.
        """
        if self.record_usage and self.usage_stats:
            return self.usage_stats.to_dict()
        return {}

    def reset_usage_data(self):
        """
        Сбрасывает накопленную статистику usage.
        """
        if self.record_usage:
            self.usage_stats = UpWorkUsageStats()
            self.logger.info("Usage stats for UpWorkClientEnhanced reset.")


# Debug usage
if __name__ == "__main__":
    base_url = "https://www.upwork.com/api/v3"
    token_url = "https://www.upwork.com/api/v3/oauth2/token"
    client_id = os.getenv("UPWORK_CLIENT_ID", "FAKE_ID")
    client_secret = os.getenv("UPWORK_CLIENT_SECRET", "FAKE_SECRET")
    scope = ["basic", "proposal"]

    client = UpWorkClient(
        base_url=base_url,
        token_url=token_url,
        client_id=client_id,
        client_secret=client_secret,
        scope=scope,
        timeout=10,
        max_retries=3,
        backoff_multiplier=2.0
    )

    try:
        jobs = client.fetch_jobs(category="Writing", limit=2)
        print("Jobs fetched:", jobs)

        if jobs:
            # handle_new_job (создаст TЗ)
            client.handle_new_job(jobs[0])

            # Допустим, дополнительное сообщение от клиента
            job_id = jobs[0]["job_id"]
            client.handle_additional_info(
                job_id, "We also want a second version with marketing style.")
            # (Опционально) create_proposal ...
            # ...
    except UpWorkError as e:
        print("[ERROR] UpWork call failed:", str(e))

    # NEW usage of UpWorkClientEnhanced
    # e_client = UpWorkClientEnhanced(
    #     base_url=base_url,
    #     token_url=token_url,
    #     client_id=client_id,
    #     client_secret=client_secret,
    #     record_usage=True
    # )
    # e_client.fetch_and_handle_jobs_enhanced("Translation", 3)
    # print("UsageData:", e_client.get_usage_data())
