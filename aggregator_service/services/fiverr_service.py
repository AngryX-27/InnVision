"""
fiverr_service.py

Новая логика для взаимодействия с Fiverr (Seller mode), когда:
 - Клиент находит ваш Gig и пишет вам в Inbox.
 - Вы читаете входящие сообщения (Inbox), анализируете, 
   при необходимости создаёте TЗ (Task Document).
 - При согласовании условий отправляете Custom Offer
   (опираясь на выбор Gig при переводе или копирайте).

В итоге:
  1) fetch_inbox_messages() — получаем диалоги из Fiverr
  2) handle_inbox_message() — анализируем сообщение, создаём/обновляем TЗ
  3) send_custom_offer() — отправляем персональное предложение.

Храним:
  - MY_GIGS (список ваших Gig'ов)
  - choose_gig_for_(...) чтобы при необходимости подобрать gig_id
"""

import logging
import time
from typing import Dict, Any, Optional, List

from aggregator_service.db import SessionLocal
from aggregator_service.logic.analyze import analyze_request
from aggregator_service.logic.tz_storage_db import create_tz, update_tz
from aggregator_service.config.config import config

# Наш клиент, работающий на низком уровне (HTTP, cookies, CSRF, etc.)
from aggregator_service.services.fiverr_client import FiverrClient, FiverrClientError

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)


class FiverrService:
    """
    Новый класс для общения через FiverrClient в Seller Mode:
      1) fetch_inbox_messages => читает входящие (Inbox).
      2) handle_inbox_message => анализирует, создаёт TЗ, 
         (при желании) отправляет кастом-оффер.
      3) send_custom_offer => высылать клиенту предложение на основе gig_id, цены, сроков.

    MY_GIGS – набор ваших Gig'ов (translation/copywriting). 
    Можно расширять при необходимости.
    """

    MY_GIGS = [
        {
            "gig_id": 1111,
            "lang_pair": ("english", "russian"),  # перевод EN->RU
            "price": 50.0,
            "delivery_days": 2
        },
        {
            "gig_id": 2222,
            "lang_pair": ("russian", "english"),  # перевод RU->EN
            "price": 55.0,
            "delivery_days": 3
        },
        {
            "gig_id": 3333,
            "lang_pair": None,  # это условно "copywriting" / universal
            "price": 40.0,
            "delivery_days": 2
        },
    ]

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
        Создаём экземпляр FiverrClient, 
        который в своей основе умеет:
         - login()
         - fetch_inbox_messages()
         - handle_inbox_message(...) 
         - send_custom_offer(...)
        """
        self.client = FiverrClient(
            username=username or config.FIVERR_USERNAME,
            password=password or config.FIVERR_PASSWORD,
            session_cookie=session_cookie or config.FIVERR_COOKIE,
            csrf_token=csrf_token or config.FIVERR_CSRF_TOKEN,
            max_retries=max_retries,
            backoff_factor=backoff_factor
        )

    ########################################################
    # Вспомогательные методы
    ########################################################
    def _find_translation_gig(self, langs: Optional[tuple]) -> Optional[int]:
        """
        Ищем Gig, подходящий для перевода (lang1->lang2). 
        Проверяем MY_GIGS, где gig['lang_pair'] совпадает (сортировка).
        """
        if not langs:
            return None
        l1, l2 = langs
        needed = tuple(sorted([l1.lower(), l2.lower()]))

        for gig_info in self.MY_GIGS:
            lp = gig_info["lang_pair"]
            if lp:
                if tuple(sorted(lp)) == needed:
                    return gig_info["gig_id"]
        return None

    def _find_copywriting_gig(self) -> Optional[int]:
        """
        Ищем Gig, где 'lang_pair' = None => условно для копирайтинга.
        """
        for gig_info in self.MY_GIGS:
            if gig_info["lang_pair"] is None:
                return gig_info["gig_id"]
        return None

    ########################################################
    # Основная "Inbox"-логика
    ########################################################
    def fetch_inbox_messages(self) -> List[Dict[str, Any]]:
        """
        Проброс к self.client.fetch_inbox_messages.
        Возвращает список диалогов: 
          [ {conversation_id, buyer_name, last_message}, ... ]
        """
        return self.client.fetch_inbox_messages()

    def handle_inbox_message(self, message_data: Dict[str, Any]) -> None:
        """
        Анализ нового сообщения. 
        - message_data: {"conversation_id":..., "buyer_name":..., "message_text":...}
        - Вызываем analyze_request => service_type, languages
        - Создаём TЗ (create_tz) или обновляем, 
          (по желанию) отправляем кастом-оффер
        """
        convo_id = message_data.get("conversation_id")
        buyer_name = message_data.get("buyer_name", "")
        text = message_data.get("message_text", "")

        analysis = analyze_request("", text)
        service_type = analysis["service_type"]
        langs = analysis["languages"]

        if not service_type:
            logger.info(
                "Conversation %s: не распознано (service_type=None).", convo_id)
            return

        order_id = f"fiverr_inbox_{convo_id}"
        initial_data = {
            "status": "draft",
            "service_type": service_type,
            "languages": langs,
            "client_updates": [
                {
                    "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                    "source": "fiverr_inbox",
                    "buyer_name": buyer_name,
                    "message_text": text
                }
            ]
        }

        with SessionLocal() as session:
            try:
                create_tz(session, order_id, initial_data)
                logger.info(
                    "Создано TЗ => order_id=%s (conversation_id=%s)", order_id, convo_id)

                # (Опционально) можем сразу решить — если "translation", находим gig:
                if service_type == "translation" and langs:
                    gig_id = self._find_translation_gig(tuple(langs))
                    if gig_id:
                        logger.info(
                            f"Можем сразу отправить custom offer на gig_id={gig_id}")
                        # self.send_custom_offer(conversation_id=convo_id, gig_id=gig_id, price=..., delivery_days=...)

                elif service_type == "copywriting":
                    gig_id = self._find_copywriting_gig()
                    if gig_id:
                        logger.info(
                            f"Можем отправить custom offer для копирайта gig_id={gig_id}")

            except Exception as e:
                logger.error("Ошибка при создании TЗ: %s", e)

    def send_custom_offer(self, conversation_id: str, gig_id: int, price: float, delivery_days: int):
        """
        Проброс к self.client.send_custom_offer (GraphQL/POST).
        """
        self.client.send_custom_offer(
            conversation_id, gig_id, price, delivery_days)

    ########################################################
    # Примерный "поток" работы через Inbox
    ########################################################
    def run_inbox_flow(self) -> None:
        """
        Демонстрация: 
          1) Авторизуемся (если нет cookie)
          2) получаем inbox_list
          3) handle_inbox_message(...) 
        """
        logger.info("Запуск run_inbox_flow (Inbox-based Fiverr approach).")

        if "fiverr_session" not in self.client._get_session_cookies():
            logger.info("Нет fiverr_session, логинимся...")
            self.client.login()

        inbox_list = self.fetch_inbox_messages()
        logger.info("Получено %d сообщений в Inbox", len(inbox_list))

        for convo in inbox_list:
            logger.info("Обрабатываем convo_id=%s, buyer=%s",
                        convo["conversation_id"], convo["buyer_name"])
            msg_data = {
                "conversation_id": convo["conversation_id"],
                "buyer_name": convo["buyer_name"],
                "message_text": convo["last_message"]
            }
            self.handle_inbox_message(msg_data)

        logger.info("run_inbox_flow завершён.")
