# orchestrator.py

import logging
import time
from typing import Optional, Dict, Any
from enum import Enum

from pydantic import BaseModel, Field

# Импорт клиентов
from services.role_general_client import (
    RoleGeneralClient, GenerateDraftRequest, GenerateDraftResponse,
    RoleClientError, RoleClientRejectedContent, RoleClientNetworkError, RoleClientAPIError
)
from services.qa_client import (
    QAClient, CheckContentRequest, QaCheckResult,
    QAClientError, QAClientRejectedContent, QAClientNetworkError
)
from services.translation_client import (
    TranslationClient, TranslationRequest, TranslationResponse,
    TranslationClientError, TranslationClientServerError, TranslationClientBadRequest
)

# SQLAlchemy
# Обычно это scoped_session ИЛИ фабрика
from aggregator_service.aggregator_db.session import aggregator_db_session
from aggregator_service.aggregator_db.models import Order  # Ваша модель

logger = logging.getLogger(__name__)

########################################################################
# 1. Статусы
########################################################################


class OrderStatus(str, Enum):
    """
    Перечисление статусов заказа при прохождении этапов:
    - ROLE_IN_PROGRESS -> ROLE_DONE
    - QA_IN_PROGRESS -> QA_DONE
    - TRANSLATION_IN_PROGRESS -> COMPLETED
    - REJECTED, FAILED при ошибках
    """
    PENDING = "pending"
    ROLE_IN_PROGRESS = "role_in_progress"
    ROLE_DONE = "role_done"
    QA_IN_PROGRESS = "qa_in_progress"
    QA_DONE = "qa_done"
    TRANSLATION_IN_PROGRESS = "translation_in_progress"
    COMPLETED = "completed"
    REJECTED = "rejected"
    FAILED = "failed"


########################################################################
# 2. Pydantic модели
########################################################################

class OrderIn(BaseModel):
    """Входная модель для обработки заказа."""
    order_id: int = Field(..., description="ID заказа в таблице orders")
    title: str = Field(..., description="Тема/название заказа")
    content: str = Field("", description="Текст (черновик)")
    language: str = Field("en", description="Исходный язык контента")
    needs_translation: bool = Field(
        False, description="Признак: нужен ли перевод?")
    skip_qa: bool = Field(False, description="Признак: пропускать ли этап QA?")


class OrderResult(BaseModel):
    """Результат обработки заказа."""
    order_id: int
    status: OrderStatus
    draft_text: Optional[str] = None
    qa_checked_text: Optional[str] = None
    final_text: Optional[str] = None
    error_message: Optional[str] = None


########################################################################
# 3. WorkflowManager
########################################################################

class WorkflowManager:
    """
    Управляет последовательностью шагов:
      Role -> QA (опционально) -> Translation (опционально).

    Обычно вызывается из Orchestrator.handle_order().

    - run_workflow() запускает всю цепочку
    - _run_role_with_retries() / _run_qa_with_retries() / _run_translation_with_retries()
      выполняют вызовы внешних сервисов с возможными повторами (retries).
    """

    def __init__(
        self,
        role_client: RoleGeneralClient,
        qa_client: QAClient,
        translation_client: TranslationClient,
        max_retries: int = 2
    ):
        """
        :param role_client: клиент для генерации черновика (RoleGeneralClient)
        :param qa_client: клиент для проверки контента (QAClient)
        :param translation_client: клиент для перевода (TranslationClient)
        :param max_retries: сколько раз повторять при сетевых ошибках
        """
        self.role_client = role_client
        self.qa_client = qa_client
        self.translation_client = translation_client
        self.max_retries = max_retries

    def run_workflow(self, order: Order, request_id: str) -> Dict[str, Any]:
        """
        Запускает цепочку:
          1) Role
          2) QA (если not order.skip_qa)
          3) Translation (если order.needs_translation)
        Возвращает словарь: {"draft_text": ..., "qa_checked_text": ..., "final_text": ...}.
        """
        results = {}

        # 1. ROLE
        order.status = OrderStatus.ROLE_IN_PROGRESS
        aggregator_db_session.commit()

        draft_text = self._run_role_with_retries(order, request_id)
        results["draft_text"] = draft_text

        # 2. QA (если не skip_qa)
        if not order.skip_qa:
            order.status = OrderStatus.QA_IN_PROGRESS
            aggregator_db_session.commit()

            qa_text = self._run_qa_with_retries(order, draft_text, request_id)
            results["qa_checked_text"] = qa_text
        else:
            logger.info(f"[{request_id}] QA пропущен (skip_qa=True).")
            qa_text = draft_text

        order.qa_checked_text = qa_text
        order.status = OrderStatus.QA_DONE
        aggregator_db_session.commit()

        # 3. Translation (если needs_translation)
        final_text = qa_text
        if order.needs_translation:
            order.status = OrderStatus.TRANSLATION_IN_PROGRESS
            aggregator_db_session.commit()

            final_text = self._run_translation_with_retries(
                order, qa_text, request_id)

        order.final_text = final_text
        aggregator_db_session.commit()

        results["final_text"] = final_text
        return results

    ######################
    # Методы c ретраями
    ######################
    def _run_role_with_retries(self, order: Order, request_id: str) -> str:
        attempt = 0
        while attempt <= self.max_retries:
            try:
                role_req = GenerateDraftRequest(
                    title=order.title,
                    language=order.language,
                    style="formal",
                    max_length=1000
                )
                resp = self.role_client.generate_draft(
                    role_req, request_id=request_id)
                logger.info(f"[{request_id}] ROLE done (attempt={attempt}).")
                order.status = OrderStatus.ROLE_DONE
                aggregator_db_session.commit()
                return resp.generated_text

            except (RoleClientNetworkError, RoleClientAPIError) as e:
                logger.warning(
                    f"[{request_id}] ROLE ошибка (attempt={attempt}): {e}")
                attempt += 1
                if attempt > self.max_retries:
                    logger.error(
                        f"[{request_id}] Превышено число попыток ROLE.")
                    raise e

            except RoleClientRejectedContent as rc:
                # Непосредственный отказ без повторных попыток
                logger.error(f"[{request_id}] ROLE отклонил контент: {rc}")
                raise rc

    def _run_qa_with_retries(self, order: Order, draft_text: str, request_id: str) -> str:
        attempt = 0
        while attempt <= self.max_retries:
            try:
                qa_req = CheckContentRequest(
                    text=draft_text, language=order.language)
                qa_resp = self.qa_client.check_content(
                    qa_req, request_id=request_id)
                logger.info(f"[{request_id}] QA done (attempt={attempt}).")

                if qa_resp.error:
                    raise QAClientRejectedContent(qa_resp.error)
                return qa_resp.checked_text

            except (QAClientNetworkError, QAClientError) as e:
                logger.warning(
                    f"[{request_id}] QA ошибка (attempt={attempt}): {e}")
                attempt += 1
                if attempt > self.max_retries:
                    logger.error(f"[{request_id}] Превышено число попыток QA.")
                    raise e

            except QAClientRejectedContent as rc:
                logger.error(f"[{request_id}] QA отклонил контент: {rc}")
                raise rc

    def _run_translation_with_retries(self, order: Order, qa_text: str, request_id: str) -> str:
        attempt = 0
        while attempt <= self.max_retries:
            try:
                target_lang = "en" if order.language != "en" else "ru"
                trans_req = TranslationRequest(
                    text=qa_text,
                    source_lang=order.language,
                    target_lang=target_lang
                )
                trans_resp = self.translation_client.translate(
                    trans_req, request_id=request_id)
                logger.info(
                    f"[{request_id}] Translation done (attempt={attempt}).")
                order.status = OrderStatus.COMPLETED
                aggregator_db_session.commit()
                return trans_resp.translated_text

            except (TranslationClientServerError, TranslationClientError) as se:
                logger.warning(
                    f"[{request_id}] Translation ошибка (attempt={attempt}): {se}")
                attempt += 1
                if attempt > self.max_retries:
                    logger.error(
                        f"[{request_id}] Превышено число попыток Translation.")
                    raise se

            except TranslationClientBadRequest as br:
                logger.error(
                    f"[{request_id}] Translation отклонил контент (BadRequest): {br}")
                raise br


########################################################################
# 4. Orchestrator
########################################################################

class Orchestrator:
    """
    Создаёт WorkflowManager, обрабатывает заказы (OrderIn),
    обновляет записи в базе (Order).

    - handle_order() проверяет наличие записи в БД, запускает WorkflowManager.run_workflow(),
      обрабатывает исключения (RejectedContent, ClientError, etc.)
    """

    def __init__(
        self,
        role_client: RoleGeneralClient,
        qa_client: QAClient,
        translation_client: TranslationClient,
        max_retries: int = 2
    ):
        """
        :param role_client: клиент Role
        :param qa_client: клиент QA
        :param translation_client: клиент Translation
        :param max_retries: число попыток при сетевых ошибках
        """
        self.workflow_manager = WorkflowManager(
            role_client, qa_client, translation_client,
            max_retries=max_retries
        )

    def handle_order(self, order_in: OrderIn, request_id: str = "no-request-id") -> 'OrderResult':
        """
        Основная точка входа:
          1. Ищем Order в БД.
          2. Обновляем данные (title, content, skip_qa и т. д.).
          3. Пытаемся выполнить run_workflow().
          4. Ловим ошибки и выставляем нужный статус (REJECTED, FAILED, ...).

        :param order_in: входные данные заказа (Pydantic-модель)
        :param request_id: уникальный ID запроса (для логгирования)
        :return: OrderResult (Pydantic)
        """
        db = aggregator_db_session  # Если scoped_session, можно сразу обращаться
        order = db.query(Order).filter_by(id=order_in.order_id).one_or_none()

        if not order:
            logger.warning(
                f"[{request_id}] Order {order_in.order_id} not found!")
            return OrderResult(
                order_id=order_in.order_id,
                status=OrderStatus.FAILED,
                error_message="Order not found"
            )

        # NEW: Если в модели Order есть поле pdf_content, можно объединить его с content:
        if hasattr(order, "pdf_content") and order.pdf_content:
            logger.info(
                f"[{request_id}] Обнаружен pdf_content (длина={len(order.pdf_content)}). Объединяем с order_in.content.")
            # Слияние (к примеру) - вы можете изменять логику в зависимости от нужд
            combined_text = (order_in.content or "") + "\n" + order.pdf_content
            order_in.content = combined_text

        # Обновляем поля
        order.title = order_in.title
        order.content = order_in.content  # мог быть дополнен pdf_text
        order.language = order_in.language
        order.needs_translation = order_in.needs_translation
        order.skip_qa = order_in.skip_qa  # при условии, что Order имеет поле skip_qa
        order.status = OrderStatus.PENDING
        db.commit()

        try:
            results = self.workflow_manager.run_workflow(order, request_id)
            order.status = OrderStatus.COMPLETED
            db.commit()

            return OrderResult(
                order_id=order.id,
                status=OrderStatus.COMPLETED,
                draft_text=results.get("draft_text"),
                qa_checked_text=results.get("qa_checked_text"),
                final_text=results.get("final_text")
            )

        except RoleClientRejectedContent as rc:
            logger.exception(f"[{request_id}] RoleClientRejectedContent: {rc}")
            order.status = OrderStatus.REJECTED
            db.commit()
            return OrderResult(
                order_id=order.id,
                status=OrderStatus.REJECTED,
                error_message=str(rc)
            )

        except QAClientRejectedContent as qc:
            logger.exception(f"[{request_id}] QAClientRejectedContent: {qc}")
            order.status = OrderStatus.REJECTED
            db.commit()
            return OrderResult(
                order_id=order.id,
                status=OrderStatus.REJECTED,
                error_message=str(qc)
            )

        except (RoleClientError, QAClientError, TranslationClientError) as ce:
            logger.exception(f"[{request_id}] Сервисная ошибка: {ce}")
            order.status = OrderStatus.FAILED
            db.commit()
            return OrderResult(
                order_id=order.id,
                status=OrderStatus.FAILED,
                error_message=str(ce)
            )

        except Exception as e:
            logger.exception(f"[{request_id}] Неизвестная ошибка: {e}")
            order.status = OrderStatus.FAILED
            db.commit()
            return OrderResult(
                order_id=order.id,
                status=OrderStatus.FAILED,
                error_message=str(e)
            )


########################################################################
# 5. Создаём orchestrator_instance (пример)
########################################################################

# Предположим, вам нужны реальные объекты клиентов:
role_client = RoleGeneralClient(api_url="http://role-general:5001")
qa_client = QAClient(api_url="http://qa-service:5003")
translation_client = TranslationClient(
    api_url="http://translation-service:5005")

# Теперь создаём единственный экземпляр Orchestrator:
orchestrator_instance = Orchestrator(
    role_client=role_client,
    qa_client=qa_client,
    translation_client=translation_client,
    max_retries=3  # Например, хотим 3 повтора
)

logger.info("orchestrator_instance создан в orchestrator.py")
