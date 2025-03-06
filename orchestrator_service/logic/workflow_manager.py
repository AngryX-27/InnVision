# workflow_manager.py

import logging
import time
from enum import Enum
from typing import Dict, Any, Optional, List, Callable

# Предположим, что у вас есть клиенты для Role, QA, Translation (с кастомными исключениями)
from services.role_general_client import (
    RoleGeneralClient, GenerateDraftRequest, GenerateDraftResponse,
    RoleClientError, RoleClientRejectedContent
)
from services.qa_client import (
    QAClient, CheckContentRequest, QaCheckResult,
    QAClientError, QAClientRejectedContent
)
from services.translation_client import (
    TranslationClient, TranslationRequest, TranslationResponse,
    TranslationClientError, TranslationClientBadRequest, TranslationClientServerError
)

# Pydantic для валидации входных/выходных данных
from pydantic import BaseModel, Field, ValidationError

logger = logging.getLogger(__name__)

########################################################################
# 1. Статусы шагов
########################################################################


class WorkflowStepStatus(str, Enum):
    NOT_STARTED = "not_started"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"

########################################################################
# 2. Модели (вход/выход) для Workflow
########################################################################


class WorkflowInput(BaseModel):
    """
    Входные данные для WorkflowManager.
    Можно дополнять нужными полями, 
    например, batch-перевод, skip_qa, ...
    """
    order_id: int = Field(..., description="Идентификатор заказа")
    title: str = Field(..., description="Заголовок/тема")
    content: str = Field("", description="Текст / ТЗ")
    language: str = Field("en", description="Исходный язык")
    need_translation: bool = Field(False, description="Нужен ли перевод?")
    skip_qa: bool = Field(False, description="Пропускать ли QA-шаг? (пример)")
    # Могут быть и другие поля: batch_texts: List[str], style, deadline и т. д.


class WorkflowOutput(BaseModel):
    """
    Итоговое состояние после прохождения всех нужных шагов.
    """
    order_id: int
    status: str  # "completed", "failed" и т. д.
    steps_status: Dict[str, str]  # { "role_generation": "completed"/... }
    draft_text: Optional[str] = None
    qa_checked_text: Optional[str] = None
    final_text: Optional[str] = None
    error: Optional[str] = None

########################################################################
# 3. Класс описывающий «шаг» Workflow
########################################################################


class WorkflowStep:
    """
    Один шаг в pipeline. 
    - name: имя
    - condition: функция(WorkflowInput)->bool, проверяющая, нужен ли этот шаг
    - action: метод, выполняющий работу (role_generation, qa_check, etc.)
    - status: текущее состояние (NOT_STARTED, IN_PROGRESS, COMPLETED, FAILED, SKIPPED)
    - retry_on_errors: список исключений, которые стоит ретраить
    - max_retries: до скольки раз пытаться
    """

    def __init__(
        self,
        name: str,
        action: Callable[..., None],
        condition: Optional[Callable[[WorkflowInput], bool]] = None,
        retry_on_errors: Optional[List[type]] = None,
        max_retries: int = 1
    ):
        self.name = name
        self.action = action
        self.condition = condition or (lambda _: True)
        self.status = WorkflowStepStatus.NOT_STARTED
        self.retry_on_errors = retry_on_errors or []
        self.max_retries = max_retries

########################################################################
# 4. WorkflowManager (расширенный)
########################################################################


class WorkflowManager:
    """
    Управляет пошаговым pipeline (Role -> QA -> Translation), с учётом:
      - Условного пропуска шагов (skip_qa, need_translation),
      - Ретраев при сетевых ошибках,
      - Логирования (timing), 
      - Выходной структуры (WorkflowOutput).
    """

    def __init__(
        self,
        role_client: RoleGeneralClient,
        qa_client: QAClient,
        translation_client: TranslationClient
    ):
        self.role_client = role_client
        self.qa_client = qa_client
        self.translation_client = translation_client

    def run_workflow(self, w_input: WorkflowInput, request_id: str = "no-request-id") -> WorkflowOutput:
        """
        Запускает pipeline шагов (динамически формируем). Возвращает WorkflowOutput.
        """
        # 1. Проверяем вход (Pydantic валидация)
        try:
            w_input = WorkflowInput(**w_input.dict())
        except ValidationError as ve:
            logger.error(
                f"[{request_id}] WorkflowInput validation error: {ve}")
            return WorkflowOutput(
                order_id=w_input.order_id,
                status="failed",
                steps_status={},
                error=f"ValidationError: {ve}"
            )

        # 2. Подготовим WorkflowOutput
        output = WorkflowOutput(
            order_id=w_input.order_id,
            status="not_started",
            steps_status={}
        )

        # 3. Список шагов — можно строить динамически,
        #    учитывая skip_qa, need_translation и т. д.
        steps = []

        # Шаг 1: role_generation
        steps.append(WorkflowStep(
            name="role_generation",
            action=lambda: self._run_role_generation(
                w_input, output, request_id),
            retry_on_errors=[RoleClientError],  # можно ретраить сетевые ошибки
            max_retries=2
        ))

        # Шаг 2: qa_check (если skip_qa=False)
        steps.append(WorkflowStep(
            name="qa_check",
            action=lambda: self._run_qa_check(w_input, output, request_id),
            condition=lambda inp: not inp.skip_qa,
            retry_on_errors=[QAClientError],
            max_retries=2
        ))

        # Шаг 3: translation (если need_translation=True)
        steps.append(WorkflowStep(
            name="translation",
            action=lambda: self._run_translation(w_input, output, request_id),
            condition=lambda inp: inp.need_translation,
            retry_on_errors=[TranslationClientServerError,
                             TranslationClientError],
            max_retries=2
        ))

        # 4. Итеративно запускаем шаги
        for step in steps:
            # Проверяем условие
            if not step.condition(w_input):
                step.status = WorkflowStepStatus.SKIPPED
                output.steps_status[step.name] = WorkflowStepStatus.SKIPPED
                logger.info(
                    f"[{request_id}] Шаг '{step.name}' пропущен (condition=False).")
                continue

            # Пытаемся выполнить с учётом ретраев
            step_attempts = 0
            success = False
            while step_attempts <= step.max_retries:
                step.status = WorkflowStepStatus.IN_PROGRESS
                output.steps_status[step.name] = step.status
                try:
                    t0 = time.monotonic()
                    logger.info(
                        f"[{request_id}] Шаг '{step.name}', attempt={step_attempts} start.")
                    step.action()
                    dt = time.monotonic() - t0
                    step.status = WorkflowStepStatus.COMPLETED
                    output.steps_status[step.name] = WorkflowStepStatus.COMPLETED
                    logger.info(
                        f"[{request_id}] Шаг '{step.name}' (attempt={step_attempts}) завершён за {dt:.2f}s.")
                    success = True
                    break
                except Exception as e:
                    step.status = WorkflowStepStatus.FAILED
                    output.steps_status[step.name] = WorkflowStepStatus.FAILED
                    logger.exception(
                        f"[{request_id}] Ошибка на шаге '{step.name}': {e}")

                    # Проверим, стоит ли ретраить
                    if any(isinstance(e, err_type) for err_type in step.retry_on_errors):
                        step_attempts += 1
                        if step_attempts > step.max_retries:
                            # Превысили
                            output.status = "failed"
                            output.error = f"{step.name} failed after {step_attempts} attempts: {e}"
                            return output
                        logger.warning(
                            f"[{request_id}] Ретраим шаг '{step.name}' (attempt={step_attempts}).")
                        time.sleep(1.0)  # небольшой бэкофф
                    else:
                        # Ошибка не из списка «ретраить» => сразу выходим
                        output.status = "failed"
                        output.error = f"{step.name} failed: {str(e)}"
                        return output

            if not success:
                # если не вышли из цикла
                output.status = "failed"
                output.error = f"{step.name} failed after all retries."
                return output

        # Если все шаги выполнились (или пропустились) без ошибок
        output.status = "completed"
        return output

    ##########################################################
    # Вспомогательные методы шагов
    ##########################################################

    def _run_role_generation(self, w_input: WorkflowInput, output: WorkflowOutput, request_id: str):
        """
        Вызываем RoleGeneralClient для генерации черновика.
        """
        role_req = GenerateDraftRequest(
            title=w_input.title,
            language=w_input.language,
            style="formal",
            max_length=1000
        )
        resp = self.role_client.generate_draft(role_req, request_id=request_id)
        output.draft_text = resp.generated_text

    def _run_qa_check(self, w_input: WorkflowInput, output: WorkflowOutput, request_id: str):
        """
        QA-проверка (если draft_text доступен).
        """
        if not output.draft_text:
            raise ValueError("Draft text отсутствует, не могу сделать QA.")
        qa_req = CheckContentRequest(
            text=output.draft_text,
            language=w_input.language
        )
        qa_resp = self.qa_client.check_content(qa_req, request_id=request_id)
        if qa_resp.error:
            raise QAClientRejectedContent(f"QA отклонил: {qa_resp.error}")
        output.qa_checked_text = qa_resp.checked_text

    def _run_translation(self, w_input: WorkflowInput, output: WorkflowOutput, request_id: str):
        """
        Перевод (если need_translation = True).
        """
        if not output.qa_checked_text:
            raise ValueError("Нет QA-проверенного текста для перевода.")
        target_lang = "en" if w_input.language.lower() != "en" else "ru"
        trans_req = TranslationRequest(
            text=output.qa_checked_text,
            source_lang=w_input.language,
            target_lang=target_lang
        )
        trans_resp = self.translation_client.translate(
            trans_req, request_id=request_id)
        output.final_text = trans_resp.translated_text


########################################################################
# Пример использования (pseudo-code)
########################################################################

# from .workflow_manager import WorkflowManager, WorkflowInput
# from services.role_general_client import RoleGeneralClient
# from services.qa_client import QAClient
# from services.translation_client import TranslationClient

# role_client = RoleGeneralClient(...)
# qa_client = QAClient(...)
# translation_client = TranslationClient(...)

# workflow_manager = WorkflowManager(
#     role_client=role_client,
#     qa_client=qa_client,
#     translation_client=translation_client
# )

# def handle_order(data: dict, request_id="no-request"):
#     w_in = WorkflowInput(**data)
#     result = workflow_manager.run_workflow(w_in, request_id=request_id)
#     # Если result.status == "completed" => ок
#     # Иначе => failed, result.error
#     return result.dict()


########################################################################
# (Опционально) Асинхронная версия (заготовка)
########################################################################

# import asyncio
# import httpx

# class AsyncWorkflowManager:
#     def __init__(self, role_client, qa_client, translation_client):
#         self.role_client = role_client
#         self.qa_client = qa_client
#         self.translation_client = translation_client

#     async def run_workflow_async(self, w_input: WorkflowInput, request_id="no-request"):
#         # Аналогичный pipeline, но await self.role_client.generate_draft_async(...)
#         ...
