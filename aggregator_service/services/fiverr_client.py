"""
fiverr_client.py

Клиент для взаимодействия с Fiverr, ориентированный на модель:
 - Клиент (Buyer) сам находит ваш Gig и пишет сообщение (Inbox)
 - Мы читаем Inbox (fetch_inbox_messages)
 - handle_inbox_message(...) при получении нового сообщения:
     * анализируем (service_type, languages)
     * создаём/обновляем TЗ (tz_storage_db)
     * при необходимости отправляем custom offer (send_custom_offer)
"""

from aggregator_service.logic.tz_storage_db import create_tz, update_tz, get_tz
from aggregator_service.logic.analyze import analyze_request
import logging
import time
from typing import Any, Dict, List, Optional
import os
import tempfile

import requests
from bs4 import BeautifulSoup

from aggregator_service.config.config import config
from aggregator_service.db import SessionLocal

from shared_lib.pdf_reader import extract_text_from_pdf

# Ваш класс ошибок, если есть


class FiverrClientError(Exception):
    pass


# Анализ (service_type, languages) - ваш анализатор

# Работа с TЗ (JSONB) в tz_storage_db


logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)


class FiverrClient:
    """
    Клиент для Fiverr (Seller Account) с логикой:
      - login() (если нужно),
      - fetch_inbox_messages(): парсинг входящих сообщений (Inbox),
      - handle_inbox_message(): анализируем, создаём/обновляем TЗ,
      - send_custom_offer(): отправляем клиенту кастомное предложение (если нужно).
    """

    def __init__(
        self,
        username: Optional[str] = None,
        password: Optional[str] = None,
        session_cookie: Optional[str] = None,
        csrf_token: Optional[str] = None,
        max_retries: int = 3,
        backoff_factor: float = 1.0
    ):
        """
        :param username: Логин на Fiverr (Seller).
        :param password: Пароль, если хотим явную авторизацию.
        :param session_cookie: fiverr_session=..., если используем готовую Cookie-сессию.
        :param csrf_token: X-CSRF-Token (если Fiverr требует при POST).
        :param max_retries: Повторы при сетевых ошибках.
        :param backoff_factor: Умножитель задержки (1.0 => 1s,2s,3s...).
        """
        self.username = username or config.FIVERR_USERNAME
        self.password = password or config.FIVERR_PASSWORD
        self.session_cookie = session_cookie or config.FIVERR_COOKIE
        self.csrf_token = csrf_token or config.FIVERR_CSRF_TOKEN
        self.max_retries = max_retries
        self.backoff_factor = backoff_factor

        self.session = requests.Session()
        self.session.headers.update({"User-Agent": "Mozilla/5.0"})

        # Если есть кука, используем её сразу
        if self.session_cookie:
            self.session.headers.update({"Cookie": self.session_cookie})
        if self.csrf_token:
            self.session.headers.update({"X-CSRF-Token": self.csrf_token})

    def login(self) -> None:
        """
        Пример авторизации на Fiverr. Если сайт требует капчу/JS - может потребоваться Selenium.
        """
        logger.info("Attempting to login to Fiverr (placeholder).")
        if not self.username or not self.password:
            raise FiverrClientError("No username/password for Fiverr login.")
        # Реальный код логина можно написать тут (POST /login, ...).
        # ...
        logger.info("Fake login done. (Placeholder)")

    def fetch_inbox_messages(self) -> List[Dict[str, Any]]:
        """
        Получаем список входящих диалогов/сообщений (Inbox).
        Fiverr UI может быть частично AJAX/GraphQL, 
        поэтому придётся парсить HTML (или sniffить GraphQL).

        Возвращаем список словарей: (conversation_id, buyer_name, last_message, ...).
        """
        # Пример URL: "https://www.fiverr.com/inbox"
        url = "https://www.fiverr.com/inbox"
        logger.info("Fetching Fiverr Inbox from %s", url)

        html = self._safe_get(url)
        if not html:
            return []

        # Пример парсинга (placeholder!)
        soup = BeautifulSoup(html, "html.parser")
        convo_items = soup.select("div.conversation-item")

        results = []
        for convo in convo_items:
            # Пример
            convo_id = convo.get("data-conversation-id", "")
            buyer_elem = convo.select_one(".buyer-username")
            buyer_name = buyer_elem.get_text(strip=True) if buyer_elem else ""
            last_msg_elem = convo.select_one(".last-message-snippet")
            last_msg = last_msg_elem.get_text(
                strip=True) if last_msg_elem else ""

            results.append({
                "conversation_id": convo_id,
                "buyer_name": buyer_name,
                "last_message": last_msg,
            })
        logger.info("Found %d Fiverr Inbox conversations", len(results))
        return results

    def handle_inbox_message(self, message_data: Dict[str, Any]) -> None:
        """
        Обрабатываем новое сообщение (или разговор):
          - message_data: { "conversation_id":..., "buyer_name":..., "message_text":... }
          - Анализируем text (service_type, langs) -> analyze_request
          - Создаём/обновляем TЗ
        """
        convo_id = message_data.get("conversation_id")
        buyer_name = message_data.get("buyer_name", "")
        text = message_data.get("message_text", "")

        # Анализ
        analysis = analyze_request("", text)  # title="", desc=text
        service_type = analysis["service_type"]
        langs = analysis["languages"]

        if not service_type:
            logger.info(
                "Conversation %s does not match known services. Skipping.", convo_id)
            return

        order_id = f"fiverr_inbox_{convo_id}" if convo_id else f"fiverr_temp_{int(time.time())}"
        initial_data = {
            "status": "draft",
            "service_type": service_type,
            "languages": langs or [],
            "client_updates": [
                {
                    "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                    "source": "fiverr_inbox",
                    "buyer_name": buyer_name,
                    "message_text": text,
                }
            ]
        }

        # Записать TЗ
        with SessionLocal() as session:
            try:
                doc = create_tz(session, order_id, initial_data)
                logger.info("TЗ создано => order_id=%s, convo=%s",
                            order_id, convo_id)

                # Если хотим автоматически отправить «custom offer»:
                # self.send_custom_offer(convo_id, gig_id=..., price=..., days=...)
                # ...

            except Exception as e:
                logger.error(
                    "Error creating TЗ doc for convo_id=%s: %s", convo_id, e)

    def send_custom_offer(self, conversation_id: str, gig_id: int, price: float, delivery_days: int) -> None:
        """
        Отправка кастомного оффера в рамках беседы (Inbox).
        :param conversation_id: ID диалога
        :param gig_id: Ваш Gig ID
        :param price: Сумма
        :param delivery_days: Срок
        """
        logger.info("Sending custom offer for convo_id=%s gig_id=%s price=%.2f days=%d",
                    conversation_id, gig_id, price, delivery_days)
        # Здесь нужно sniffить, как Fiverr отправляет Custom Offer (GraphQL/REST).
        # Пример (placeholder):
        url = "https://www.fiverr.com/graphql"
        headers = self.session.headers.copy()
        body = {
            "operationName": "CreateCustomOffer",
            "variables": {
                "conversationId": conversation_id,
                "gigId": gig_id,
                "price": price,
                "deliveryTime": delivery_days
            },
            "query": """
            mutation CreateCustomOffer($conversationId: String!, $gigId: Int!, $price: Float!, $deliveryTime: Int!) {
              createCustomOffer(
                conversationId: $conversationId,
                gigId: $gigId,
                price: $price,
                deliveryTime: $deliveryTime
              ) {
                success
                offerId
                error {
                  code
                  message
                }
              }
            }
            """
        }

        # Попытка отправить
        try:
            resp = self.session.post(
                url, json=body, headers=headers, timeout=20)
            resp.raise_for_status()
            data = resp.json()
            if "errors" in data:
                raise FiverrClientError(f"GraphQL errors: {data['errors']}")

            mutation_data = data.get("data", {}).get("createCustomOffer", {})
            if not mutation_data.get("success"):
                err = mutation_data.get("error", {})
                msg = err.get(
                    "message", "Неизвестная ошибка при отправке custom offer")
                raise FiverrClientError(msg)

            logger.info("Custom Offer sent successfully (placeholder).")

            # (Опционально) Обновляем TЗ
            with SessionLocal() as session:
                order_id = f"fiverr_inbox_{conversation_id}"
                try:
                    update_tz(session, order_id, {
                        "offer_sent": {
                            "gig_id": gig_id,
                            "price": price,
                            "delivery_days": delivery_days,
                            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
                        }
                    })
                    logger.info(
                        "Updated TЗ with offer_sent details for order_id=%s", order_id)
                except Exception as e:
                    logger.warning(
                        "Could not update TЗ for order_id=%s: %s", order_id, e)

        except requests.RequestException as e:
            raise FiverrClientError(
                f"Сетевая ошибка при отправке custom offer: {e}")

    def handle_pdf_attachments(self, message_data: Dict[str, Any], order_id: str):
        """
        Ищем PDF-файлы (если клиент прикрепил в сообщении).
        Скачиваем, запускаем extract_text_from_pdf, 
        и добавляем их содержимое в TЗ (pdf_content).
        :param message_data: {"attachments": [...], ...}
        :param order_id: уже созданный order_id (f"fiverr_inbox_{convo_id}" если convo_id есть).
        """
        attachments = message_data.get("attachments", [])
        if not attachments:
            self.logger.info(
                "No attachments in message_data for order_id=%s", order_id)
            return

        self.logger.info(
            "Checking PDF attachments for order_id=%s ...", order_id)
        with SessionLocal() as session:
            for att in attachments:
                file_type = att.get("file_type", "").lower()  # e.g. "pdf"
                file_url = att.get("url")                    # URL to download
                file_name = att.get("file_name", "attachment.pdf")

                if "pdf" in file_type:
                    # 1) Скачиваем PDF
                    pdf_path = self._download_pdf_fiverr(file_url, file_name)
                    if not pdf_path:
                        self.logger.warning(
                            "Could not download PDF: %s", file_url)
                        continue

                    # 2) Извлекаем текст
                    pdf_text = extract_text_from_pdf(pdf_path)
                    # 3) Обновляем TЗ (добавляем pdf_content)
                    updates = {
                        "pdf_content": [
                            {
                                "file_name": file_name,
                                "url": file_url,
                                # limit to 2000 chars
                                "extracted_text": pdf_text[:2000]
                            }
                        ]
                    }
                    try:
                        update_tz(session, order_id, updates)
                        self.logger.info(
                            "PDF extracted & updated TЗ => order_id=%s file=%s", order_id, file_name)
                    except Exception as e:
                        self.logger.warning(
                            "Could not update TЗ with PDF content for order_id=%s: %s", order_id, e)
                else:
                    self.logger.debug(
                        "Skipping non-PDF attachment: %s - %s", file_type, file_name)

    def _download_pdf_fiverr(self, file_url: str, file_name: str) -> Optional[str]:
        """
        Скачивает PDF-файл по прямой ссылке file_url, сохраняет 
        временно (tmpdir). Возвращает локальный путь или None.
        """
        if not file_url.startswith("http"):
            self.logger.warning("Invalid PDF file_url=%s", file_url)
            return None

        try:
            resp = requests.get(file_url, timeout=15)
            resp.raise_for_status()

            tmp_dir = tempfile.gettempdir()
            pdf_path = os.path.join(tmp_dir, file_name)
            with open(pdf_path, "wb") as f:
                f.write(resp.content)

            self.logger.info("Downloaded PDF => %s", pdf_path)
            return pdf_path
        except Exception as e:
            self.logger.error("Error downloading PDF from %s: %s", file_url, e)
            return None

    def _safe_get(self, url: str) -> str:
        """
        GET-запрос с ретраями, возвращает HTML-текст (или пустую строку при ошибках).
        """
        attempt = 0
        while True:
            try:
                attempt += 1
                resp = self.session.get(url, timeout=20)
                if resp.status_code >= 400:
                    logger.error("HTTP %s from %s", resp.status_code, url)
                    if resp.status_code in [429, 500, 502, 503, 504] and attempt <= self.max_retries:
                        sleep_time = self.backoff_factor * attempt
                        logger.info("Retry GET %d/%d in %.1f s",
                                    attempt, self.max_retries, sleep_time)
                        time.sleep(sleep_time)
                        continue
                    return ""
                return resp.text
            except requests.exceptions.RequestException as e:
                logger.error("Network error on GET %s: %s", url, e)
                if attempt <= self.max_retries:
                    time.sleep(self.backoff_factor * attempt)
                    continue
                return ""


# Example usage (debug)
if __name__ == "__main__":
    fc = FiverrClient()
    # fc.login()  # Если нужно
    inbox_list = fc.fetch_inbox_messages()
    logger.info("Fetched %d convos from Inbox", len(inbox_list))

    for convo in inbox_list:
        # Имитируем, что взяли 'last_message' => handle_inbox_message
        message_data = {
            "conversation_id": convo["conversation_id"],
            "buyer_name": convo["buyer_name"],
            "message_text": convo["last_message"]
        }
        fc.handle_inbox_message(message_data)

    # Пример отправки кастомного оффера
    # fc.send_custom_offer(conversation_id="abc123", gig_id=1111, price=50, delivery_days=3)
