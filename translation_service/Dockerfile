# =========================== STAGE 1: BUILDER ==============================
# Если вы хотите собирать колёсики (wheels) и устанавливать их
FROM python:3.11-slim AS builder

# Переменные окружения для более быстрого pip
ENV PIP_NO_CACHE_DIR=1 \
  PYTHONDONTWRITEBYTECODE=1 \
  PYTHONUNBUFFERED=1

# Добавляем libpq-dev, чтобы psycopg2 мог собраться (pg_config).
# build-essential уже есть, оставляем для компиляции.
RUN apt-get update && apt-get install -y --no-install-recommends \
  build-essential \
  libpq-dev \
  && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Скопируем и установим зависимости
# (Если у вас poetry/pyproject, скорректируйте)
COPY requirements.txt ./
RUN pip install --upgrade pip wheel setuptools
RUN pip wheel --wheel-dir=/wheels -r requirements.txt

# ======================= STAGE 2: RUNTIME/FINAL ============================
FROM python:3.11-slim

# создаём непривилегированного пользователя
RUN useradd -m -u 1001 appuser

ENV PIP_NO_CACHE_DIR=1 \
  PYTHONDONTWRITEBYTECODE=1 \
  PYTHONUNBUFFERED=1

# NEW: Устанавливаем libpq5 (или postgresql-libs), а также build-essential и libpq-dev,
#     чтобы psycopg2 мог собраться (pg_config).
# NEW: Дополнительно poppler-utils, tesseract-ocr для PDF (OCR).
RUN apt-get update && apt-get install -y --no-install-recommends \
  libpq5 \
  build-essential \
  libpq-dev \
  poppler-utils \
  tesseract-ocr \
  && rm -rf /var/lib/apt/lists/*

# Копируем папку keys именно в /app/keys
COPY keys /app/keys

WORKDIR /app

# 1) Скопируем aggregator_service в /app/aggregator_service
COPY aggregator_service /app/aggregator_service

# 2) Скопируем сам код translation_service
COPY translation_service /app/translation_service

# (Если aggregator_service имеет свои зависимости)
# RUN pip install -r aggregator_service/requirements.txt

# (Если translation_service имеет requirements)
RUN pip install --default-timeout=1500 -r translation_service/requirements.txt

RUN pip install --no-cache-dir -r aggregator_service/requirements.txt

# Скопируем колёсики из builder-слоя и установим
COPY --from=builder /wheels /wheels
RUN pip install /wheels/*

# Следующая строка "COPY . /app" может перезаписать уже скопированные файлы,
# если в корне . есть aggregator_service/ или keys/.
# Но согласно вашему требованию "ничего не убирать" — оставляем.
COPY . /app

# NEW: Создаём папку /app/logs, выдаём права пользователю appuser
RUN mkdir -p /app/logs && chown -R appuser:appuser /app/logs

# NEW: Устанавливаем Python-библиотеки для PDF (PyPDF2, pdfplumber, pytesseract),
# если они не в requirements. Если уже прописаны в requirements.txt, можно пропустить:
RUN pip install --no-cache-dir PyPDF2 pdfplumber pytesseract

# Переключаемся на непривилегированного пользователя
USER appuser

# Откройте порт (если FastAPI/Flask на 5005)
EXPOSE 5005

# Если у вас .env, возможно вы копируете его тоже. Но лучше передавать ENV через docker-compose.

# Опционально: если хотите встроенный healthcheck (чаще в docker-compose.yml указывают)
# HEALTHCHECK --interval=30s --timeout=5s --retries=3 CMD curl -f http://localhost:5005/health || exit 1

# Запуск приложения
# Предположим, что у вас FastAPI-приложение в файле main.py c переменной app:
CMD ["uvicorn", "translation_service.app:app", "--host", "0.0.0.0", "--port", "5005"]