# =========================== STAGE 1: BUILDER ==============================
FROM python:3.11-slim AS builder

# NEW: Отключаем кэш pip и отключаем pyc/буферизацию
ENV PIP_NO_CACHE_DIR=1 \
  PYTHONDONTWRITEBYTECODE=1 \
  PYTHONUNBUFFERED=1

# NEW: Устанавливаем системные зависимости для сборки psycopg2 (libpq-dev, gcc)
RUN apt-get update && apt-get install -y --no-install-recommends \
  build-essential \
  libpq-dev \
  && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# (Ваша исходная строка) - копируем requirements
COPY requirements.txt ./

# (Ваша исходная строка) - обновляем pip, wheel
RUN pip install --upgrade pip wheel setuptools

# (Ваша исходная строка) - собираем колёсики
RUN pip wheel --wheel-dir=/wheels -r requirements.txt

# ======================= STAGE 2: RUNTIME/FINAL ============================
FROM python:3.11-slim

# NEW: создаём непривилегированного пользователя
RUN useradd -m -u 1001 appuser

ENV PIP_NO_CACHE_DIR=1 \
  PYTHONDONTWRITEBYTECODE=1 \
  PYTHONUNBUFFERED=1

# NEW: Устанавливаем libpq5 (для psycopg2) + poppler-utils/tesseract-ocr для PDF
RUN apt-get update && apt-get install -y --no-install-recommends \
  libpq5 \
  poppler-utils \
  tesseract-ocr \
  && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# (Ваша исходная строка) - копируем колёсики из builder
COPY --from=builder /wheels /wheels
RUN pip install /wheels/*

# (Ваша исходная строка) - копируем весь код
COPY . /app

# NEW: Устанавливаем Python-библиотеки для работы с PDF (если нет в requirements)
# Если PyPDF2, pdfplumber, pytesseract уже в requirements.txt, эту строку можно убрать.
RUN pip install --no-cache-dir PyPDF2 pdfplumber pytesseract

# (Ваша исходная строка) - переключаемся на пользователя
USER appuser

# (Ваша исходная строка) - если Orchestrator слушает порт 5000 (пример)
EXPOSE 5000

# (Ваша исходная строка) - запуск приложения
# Предположим, что у вас Flask или FastAPI (корректируйте по своему сценарию)
CMD ["python", "app.py"]