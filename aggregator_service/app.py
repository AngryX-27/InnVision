"""
app.py

Расширенная версия FastAPI-приложения для Aggregator Service.
Предполагает микросервис, который:
  - В фоне (через отдельный поток) обрабатывает заказы с UpWork и Fiverr
  - Предварительно сохраняет их в БД (PostgreSQL)
  - При необходимости использует GPTService для генерации/перевода
  - Предоставляет эндпоинты /health, /policy-qa и т.д.

Запуск (dev-режим):
    python app.py
Или через uvicorn/gunicorn:
    uvicorn aggregator_service.app:app --host 0.0.0.0 --port 5002

Автор: (Ваша команда)
"""

from aggregator_service.logic.tz_storage_db import finalize_tz, get_tz, list_tz_documents
import signal
import time
import uuid
import threading
import datetime

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

# NEW: Импорт logging, если хотим
import logging

# Исходные импорты (не удаляем)
from aggregator_service.logic.tz_storage_db import list_tz_documents
from aggregator_service.logic.tz_storage_db import finalize_tz, get_tz
from aggregator_service.logic.orchestrator_dispatcher import send_tz_to_orchestrator

from aggregator_service.config.config import (
    logger,                # <-- Предполагаем, что 'logger' уже есть
    MAIN_INTERVAL,
    UPWORK_API_URL,
    UPWORK_ACCESS_TOKEN
)
from aggregator_service.db import SessionLocal
from aggregator_service.services.upwork_client import UpWorkClient
from aggregator_service.services.gpt_service import GPTService
from aggregator_service.services.fiverr_service import FiverrService

# Пример: если есть Orchestrator, можно импортировать его,
# но обычно он в отдельном микросервисе.

# ===================================================
# Глобальные переменные и метрики
# ===================================================
stop_running = False          # Флаг для фонового цикла (остановка)
aggregator_count = 0          # Сколько раз мы запускали агрегатор
aggregator_last_run = None    # Когда последний раз успешно отработали
aggregator_last_error = None  # Текст последней ошибки
startup_time = datetime.datetime.utcnow()  # Время запуска приложения

# NEW: Логируем, что app.py инициализируется
logger.info("Инициализация app.py (Aggregator).")

# ===================================================
# Обработка сигналов (SIGINT, SIGTERM)
# ===================================================


def handle_signal(sig, frame):
    """
    Перехватываем сигналы SIGTERM/SIGINT, чтобы корректно завершить цикл агрегатора.
    """
    global stop_running
    stop_running = True
    logger.info(
        f"[SignalHandler] Получен сигнал {sig}. Останавливаем агрегатор...")


signal.signal(signal.SIGTERM, handle_signal)
signal.signal(signal.SIGINT, handle_signal)

# ===================================================
# Инициализация UpWorkClient, FiverrService и GPTService
# ===================================================


def initialize_upwork_client():
    """
    Создаёт и возвращает UpWorkClient.
    Предполагается, что в config.py есть UPWORK_API_URL, UPWORK_ACCESS_TOKEN.
    """
    logger.info("Initializing UpWork client...")
    client = UpWorkClient(
        base_url=UPWORK_API_URL,
        token=UPWORK_ACCESS_TOKEN,
        logger=logger
    )
    return client


def initialize_fiverr_service():
    """
    Создаёт и возвращает FiverrService.
    FiverrService внутри себя поднимает FiverrClient.
    Настройки (логин/пароль/куки) должны быть в config.py или .env.
    """
    logger.info("Initializing Fiverr service...")
    # При необходимости передадим параметры, например:
    service = FiverrService(
        username=None,  # возьмёт из settings
        password=None,
        session_cookie=None,
        max_retries=3,
        backoff_factor=1.0
    )
    return service


def initialize_gpt_service():
    """
    Создаёт и возвращает GPTService (примем gpt-4 либо другую модель).
    """
    logger.info("Initializing GPTService...")
    service = GPTService(
        model="gpt-4",
        temperature=0.7,
        max_tokens=500,
        logger=logger,
        retry_count=3,
        retry_delay=3
    )
    return service

# ===================================================
# Дополнительная логика UpWork (пример)
# ===================================================


def process_upwork_orders_advanced(session, upwork_client, gpt_service, trace_id: str):
    """
    Пример функции, которая выполняет более углублённую работу с UpWork:
      - Получает новые заказы (jobs)
      - Применяет фильтрацию
      - Формирует заявку (proposal) через GPT или шаблон
      - При необходимости отправляет заявку через UpWorkClient
      - Сохраняет результаты в БД (через session)

    :param session: SQLAlchemy сессия
    :param upwork_client: клиент для UpWork
    :param gpt_service: сервис GPT, если нужно генерировать текст
    :param trace_id: идентификатор для логирования
    """
    logger.info(
        f"[UpWorkAdv] Начинаем расширенную обработку UpWork заказов. trace_id={trace_id}")

    # 1) Получаем заказы (примерная функция, нужно реализовать в upwork_client)
    # <-- предполагается, что у вас есть метод fetch_new_jobs
    new_jobs = upwork_client.fetch_new_jobs()
    logger.info(
        f"[UpWorkAdv] Получено {len(new_jobs)} потенциальных заказов с UpWork.")

    # 2) Фильтрация (пример: только для перевода EN->RU, бюджет > 50)
    filtered = []
    for job in new_jobs:
        if "translate" in job.get("title", "").lower() or "translation" in job.get("title", "").lower():
            if job.get("budget", 0) >= 50:
                filtered.append(job)

    logger.info(
        f"[UpWorkAdv] После фильтрации осталось {len(filtered)} заказов.")

    # 3) Формируем заявки (proposal) - можно использовать GPT
    for job in filtered:
        # Пример генерации:
        prompt_messages = [
            {"role": "system", "content": "You are an AI specialized in writing proposals for translation jobs."},
            {"role": "user",
             "content": f"Write a short cover letter for this job:\nTitle: {job.get('title')}\nDescription: {job.get('description')}\nBudget: {job.get('budget')}."}
        ]
        cover_letter = gpt_service.generate_chat_completion(prompt_messages)

        logger.info(
            f"[UpWorkAdv] Сформирован cover_letter для job {job['id']}: {cover_letter[:60]}...")

        # 4) Отправка заявки через UpWorkClient (пример)
        # upwork_client.send_proposal(job_id=job["id"], proposal_text=cover_letter)

        # 5) Сохраняем в БД (пример) - допустим, у вас модель Order
        """
        new_order = Order(
            external_id=job["id"],
            source="upwork",
            title=job["title"],
            budget=job["budget"],
            status="proposal_sent",
            cover_letter=cover_letter,
            created_at=datetime.datetime.utcnow()
        )
        session.add(new_order)
        """

    # 6) session.commit() если нужно
    logger.info("[UpWorkAdv] Завершена расширенная обработка заказов UpWork.")

# ===================================================
# Агрегатор (процесс) — вызываем UpWork и Fiverr
# ===================================================


def aggregator_cycle(session, upwork_client, fiverr_service, gpt_service):
    """
    Логика одного цикла «обработки заказов»:
      - Запускаем fiverr_service.run_full_flow()
      - Запускаем process_upwork_orders_advanced()
      - При успехе увеличиваем счётчик aggregator_count
      - При ошибке фиксируем aggregator_last_error
    """
    global aggregator_count, aggregator_last_run, aggregator_last_error

    trace_id = str(uuid.uuid4())[:8]
    logger.info(f"[Aggregator] Starting aggregator cycle. trace_id={trace_id}")

    try:
        # Fiverr flow
        fiverr_service.run_full_flow()

        # UpWork flow
        process_upwork_orders_advanced(
            session, upwork_client, gpt_service, trace_id)

        aggregator_count += 1
        aggregator_last_run = datetime.datetime.utcnow()
        aggregator_last_error = None
        logger.info("[Aggregator] Cycle complete.")

    except Exception as e:
        logger.error("Ошибка в aggregator_cycle", exc_info=True)
        aggregator_last_error = str(e)


def aggregator_loop(upwork_client, fiverr_service, gpt_service):
    """
    Бесконечный цикл, запускаемый в отдельном потоке:
      - Каждые MAIN_INTERVAL секунд запускаем aggregator_cycle
      - Останавливаемся, если stop_running == True (сигнал на завершение)
    """
    logger.info("[Aggregator] Background thread started.")
    while not stop_running:
        with SessionLocal() as session:
            aggregator_cycle(session, upwork_client,
                             fiverr_service, gpt_service)

        # Ждём MAIN_INTERVAL, проверяя stop_running
        for _ in range(MAIN_INTERVAL):
            if stop_running:
                break
            time.sleep(1)

    logger.info("[Aggregator] Background thread shutting down...")


def check_db_connection():
    """
    Пытается выполнить простой SELECT 1 в БД.
    Возвращает (True, None), если всё ок,
    либо (False, описание_ошибки) в случае неудачи.
    """
    try:
        with SessionLocal() as session:
            session.execute("SELECT 1")
        return True, None
    except Exception as e:
        return False, str(e)


class PolicyQuestion(BaseModel):
    question: str


# Создаём приложение FastAPI
app = FastAPI(
    title="Aggregator Service (Extended)",
    description="Сервис, который в фоне агрегирует заказы с UpWork и Fiverr, обрабатывает их и хранит в БД.",
    version="1.1.0"
)

# Инициализируем основные сервисы и фиксируем время старта
upwork_client = initialize_upwork_client()
fiverr_service = initialize_fiverr_service()
gpt_service = initialize_gpt_service()
startup_time = datetime.datetime.utcnow()


@app.on_event("startup")
def start_aggregator_thread():
    """
    При запуске приложения FastAPI создаём фоновый поток, в котором
    крутится aggregator_loop(...).
    """
    aggregator_thread = threading.Thread(
        target=aggregator_loop,
        args=(upwork_client, fiverr_service, gpt_service),
        daemon=True
    )
    aggregator_thread.start()
    logger.info("Aggregator thread launched in background.")


@app.on_event("shutdown")
def shutdown_event():
    """
    При завершении приложения шлём сигнал stop_running = True,
    чтобы фоновый поток завершил цикл.
    """
    global stop_running
    stop_running = True
    logger.info("FastAPI shutdown event. Aggregator loop signalled to stop.")
    time.sleep(2)


@app.get("/health")
def healthcheck():
    """
    Расширенный healthcheck, который проверяет состояние БД,
    статус агрегатора и время работы приложения.
    """
    db_ok, db_err = check_db_connection()
    status = "ok"
    msg = "All good"

    if not db_ok:
        status = "degraded"
        msg = f"DB error: {db_err}"
    elif aggregator_last_error:
        status = "degraded"
        msg = f"Aggregator error: {aggregator_last_error}"

    uptime_seconds = (datetime.datetime.utcnow() -
                      startup_time).total_seconds()

    return {
        "status": status,
        "message": msg,
        "db_connection": "ok" if db_ok else "error",
        "db_error": db_err,
        "aggregator_count": aggregator_count,
        "aggregator_last_run": aggregator_last_run.isoformat() if aggregator_last_run else None,
        "aggregator_last_error": aggregator_last_error,
        "uptime_seconds": uptime_seconds
    }


@app.post("/policy-qa")
def ask_policy(payload: PolicyQuestion):
    """
    Пример эндпоинта, который якобы отвечает на вопросы по «Политике».
    Пока выводим заглушку.
    """
    return {
        "answer": f"Заглушка: вопрос '{payload.question}' (Policy QA не настроен)."
    }


def finalize_and_dispatch_order(order_id: str, final_text: str = "Confirmed by aggregator"):
    """
    1) finalize_tz(session, order_id, final_text)
    2) send_tz_to_orchestrator(order_id)
    Возвращает ответ оркестратора либо ошибку.
    """
    logger.info("Finalize & dispatch for order_id=%s, text=%r",
                order_id, final_text)
    with SessionLocal() as session:
        try:
            finalize_tz(session, order_id, final_text)
        except ValueError as e:
            logger.error("No TЗ for order_id=%s? %s", order_id, e)
            return {"error": str(e)}

    resp = send_tz_to_orchestrator(order_id)
    logger.info("Orchestrator response for order_id=%s => %s", order_id, resp)
    return resp


@app.post("/finalize-dispatch/{order_id}")
def finalize_dispatch(order_id: str):
    """
    Эндпоинт: финализирует TЗ (ставит status='confirmed', final_text='Confirmed by aggregator'),
    затем отправляет в Оркестратор (POST /orders).
    Возвращает ответ оркестратора.
    """
    orchestrator_resp = finalize_and_dispatch_order(
        order_id, "Confirmed by aggregator")
    return {"orchestrator_response": orchestrator_resp}


@app.get("/tz/{order_id}")
def view_tz(order_id: str):
    """
    Пример эндпоинта для просмотра текущего TЗ-документа (JSONB) по order_id.
    Удобно для отладки.
    """
    with SessionLocal() as session:
        tz_data = get_tz(session, order_id)
    if not tz_data:
        return {"error": "No TЗ found", "order_id": order_id}
    return {"order_id": order_id, "tz_data": tz_data}


@app.get("/tz")
def list_all_tz(limit: int = 50, offset: int = 0):
    """
    Показывает список TЗ-документов (из tz_storage_db) — максимум limit.
    """
    with SessionLocal() as session:
        docs = list_tz_documents(session, limit=limit, offset=offset)
    return {
        "count": len(docs),
        "limit": limit,
        "offset": offset,
        "tz_docs": docs
    }


# NEW: Пример управляющих эндпоинтов для управления «покусом» агрегатора.
# Если они вам не нужны, можно убрать, но кода не удаляем :)
@app.post("/aggregator/pause")
def pause_aggregator():
    """
    Пример: принудительно ставим stop_running = True,
    чтобы приостановить дальнейшие циклы.
    """
    global stop_running
    stop_running = True
    logger.warning(
        "Aggregator has been paused via /aggregator/pause endpoint.")
    return {"status": "paused", "message": "Aggregator loop is stopped."}


@app.post("/aggregator/resume")
def resume_aggregator():
    """
    Пример: перезапускаем поток агрегатора, если он был остановлен.
    Для полноты примера — можно учесть, что если поток «мертв», надо создать новый.
    """
    global stop_running
    if not stop_running:
        logger.info("Aggregator is already running.")
        return {"status": "running", "message": "Aggregator is already active."}

    stop_running = False
    logger.warning(
        "Aggregator is being resumed via /aggregator/resume endpoint.")

    # Запускаем новый поток, потому что старый цикл завершился
    aggregator_thread = threading.Thread(
        target=aggregator_loop,
        args=(upwork_client, fiverr_service, gpt_service),
        daemon=True
    )
    aggregator_thread.start()
    return {"status": "resumed", "message": "Aggregator loop resumed in new thread."}


if __name__ == "__main__":
    import uvicorn
    logger.info("Запуск UVicorn (dev). Для продакшена лучше Gunicorn.")
    uvicorn.run(
        app,
        host="0.0.0.0",
        port=5002,
        log_level="info"
    )
