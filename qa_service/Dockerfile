# ====================== STAGE 1: BUILDER ==========================
FROM python:3.11-slim AS builder

ENV PIP_NO_CACHE_DIR=1 \
  PYTHONDONTWRITEBYTECODE=1 \
  PYTHONUNBUFFERED=1

# NEW: Добавляем libpq-dev и build-essential для сборки psycopg2
RUN apt-get update && apt-get install -y --no-install-recommends \
  build-essential \
  libpq-dev \
  && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Копируем список зависимостей
COPY requirements.txt ./

# Обновляем pip, wheel и прочее
RUN pip install --upgrade pip wheel setuptools

# Собираем wheel-пакеты и сохраняем в /wheels
RUN pip wheel --wheel-dir=/wheels -r requirements.txt

# ====================== STAGE 2: FINAL ============================
FROM python:3.11-slim

# NEW: создаём непривилегированного пользователя
RUN useradd -m -u 1001 appuser

ENV PIP_NO_CACHE_DIR=1 \
  PYTHONDONTWRITEBYTECODE=1 \
  PYTHONUNBUFFERED=1

# NEW: Устанавливаем libpq5 + инструменты для PDF (poppler-utils, tesseract-ocr)
RUN apt-get update && apt-get install -y --no-install-recommends \
  openjdk-17-jre \
  libpq5 \
  poppler-utils \
  tesseract-ocr \
  && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Копируем wheel-пакеты из builder-слоя
COPY --from=builder /wheels /wheels
RUN pip install /wheels/*

# Копируем код qa_service
COPY . /app

# NEW: Устанавливаем Python-библиотеки для PDF (если нет в requirements).
# Если PyPDF2, pdfplumber, pytesseract уже есть в requirements.txt, 
# то эту строку можно убрать:
RUN pip install --no-cache-dir PyPDF2 pdfplumber pytesseract

# Переключаемся на непривилегированного пользователя
USER appuser

# Открываем порт (QA_SERVICE_PORT обычно 5003)
EXPOSE 5003

# Запуск приложения (зависит от вашего QA-кода: Flask? FastAPI? plain Python?)
CMD ["python", "app.py"]