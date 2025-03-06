# =========================== STAGE 1: BUILDER ============================
FROM python:3.11-slim AS builder

# NEW: Отключаем кэш pip и отключаем pyc
ENV PIP_NO_CACHE_DIR=1 \
  PYTHONDONTWRITEBYTECODE=1 \
  PYTHONUNBUFFERED=1

# NEW: Устанавливаем системные пакеты для сборки psycopg2
RUN apt-get update && apt-get install -y --no-install-recommends \
  build-essential \
  libpq-dev \
  && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# (Ваша строка): копируем requirements
COPY requirements.txt ./

# (Ваша строка): обновляем pip, wheel
RUN pip install --upgrade pip wheel setuptools

# (Ваша строка): собираем колёсики
RUN pip wheel --wheel-dir=/wheels -r requirements.txt

# =========================== STAGE 2: FINAL/RUNTIME ============================
FROM python:3.11-slim

# NEW: создаём непривилегированного пользователя
RUN useradd -m -u 1001 appuser

ENV PIP_NO_CACHE_DIR=1 \
  PYTHONDONTWRITEBYTECODE=1 \
  PYTHONUNBUFFERED=1

# NEW: Устанавливаем libpq5 (для уже собранного psycopg2)
# NEW: Дополнительно: poppler-utils (pdfimages) + tesseract-ocr для OCR PDF
RUN apt-get update && apt-get install -y --no-install-recommends \
  libpq5 \
  poppler-utils \
  tesseract-ocr \
  && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# (Ваша строка): копируем колёсики из builder
COPY --from=builder /wheels /wheels
RUN pip install /wheels/*

# (Ваша строка): копируем весь код
COPY . /app

# NEW: Устанавливаем Python-библиотеки для работы с PDF
# (Если они ещё не включены в requirements.txt:
#  PyPDF2, pdfplumber, pytesseract и т.д.)
RUN pip install --no-cache-dir PyPDF2 pdfplumber pytesseract

# (Ваша строка): переключаемся на пользователя
USER appuser

# (Ваша строка): EXPOSE, если Aggregator слушает 5002 (пример)
EXPOSE 5002

# (Ваша строка): команда запуска
# Если Aggregator — FastAPI/Flask, используйте uvicorn/gunicorn, иначе python app.py
CMD ["python", "app.py"]