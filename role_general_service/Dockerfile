# ======================= STAGE 1: BUILDER ========================
FROM python:3.11-slim AS builder

ENV PIP_NO_CACHE_DIR=1 \
  PYTHONDONTWRITEBYTECODE=1 \
  PYTHONUNBUFFERED=1

# NEW: Устанавливаем системные пакеты для сборки (libpq-dev + build-essential).
#      build-essential уже у вас есть, добавим libpq-dev,
#      чтобы psycopg2 мог собраться с pg_config.
RUN apt-get update && apt-get install -y --no-install-recommends \
  build-essential \
  libpq-dev \
  && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Копируем requirements.txt
COPY requirements.txt ./

# Обновляем pip и собираем колёсики (wheels)
RUN pip install --upgrade pip wheel setuptools
RUN pip wheel --wheel-dir=/wheels -r requirements.txt

# ======================= STAGE 2: FINAL ==========================
FROM python:3.11-slim

# Создаём непривилегированного пользователя (appuser)
RUN useradd -m -u 1001 appuser

ENV PIP_NO_CACHE_DIR=1 \
  PYTHONDONTWRITEBYTECODE=1 \
  PYTHONUNBUFFERED=1

# NEW: Для работы собранного psycopg2 в рантайме нужен libpq (драйвер Postgres).
#      В Debian/Ubuntu это пакет libpq5. Устанавливаем без лишних зависимостей.
# NEW: Дополнительно, чтобы роль-генерал мог читать PDF (OCR):
#      poppler-utils (pdfimages) и tesseract-ocr
RUN apt-get update && apt-get install -y --no-install-recommends \
  libpq5 \
  poppler-utils \
  tesseract-ocr \
  && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Копируем собранные колёсики из builder-слоя
COPY --from=builder /wheels /wheels
RUN pip install /wheels/*

# Копируем код микросервиса
COPY . /app

# NEW: Устанавливаем Python-библиотеки для PDF (если нет в requirements).
# Если PyPDF2, pdfplumber, pytesseract уже перечислены в requirements.txt,
# эту строку можно опустить:
RUN pip install --no-cache-dir PyPDF2 pdfplumber pytesseract

# Переключаемся на непривилегированного пользователя
USER appuser

EXPOSE 5001

# Если ваше приложение — Flask или FastAPI, используйте Gunicorn/uvicorn,
# иначе, если app.py это просто точка входа с Flask.run(...):
CMD ["python", "app.py"]