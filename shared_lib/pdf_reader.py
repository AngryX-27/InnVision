"""
pdf_reader.py

Универсальный модуль для извлечения текста из PDF:
  1) Пытается PyPDF2 (или pdfplumber), чтобы получить "text layer".
  2) Если текст получен (не пусто), возвращаем его.
  3) Если текст пуст (скан), используем OCR (tesseract) + pdfimages.
  4) Склеиваем всё в одну строку, возвращаем.

Требования:
  - PyPDF2>=3.0 (или pdfplumber) в requirements.txt
  - Для OCR: tesseract и poppler-utils (pdfimages) в системе
"""

import logging
import os
import subprocess
import tempfile
import shutil

from typing import Optional

try:
    import PyPDF2
except ImportError:
    PyPDF2 = None

try:
    import pdfplumber
except ImportError:
    pdfplumber = None

logger = logging.getLogger(__name__)


def extract_text_from_pdf(
    pdf_path: str,
    use_pdfplumber: bool = False,
    do_ocr: bool = True
) -> str:
    """
    Извлекает текст из PDF. Алгоритм:
      1) Попробовать PyPDF2 (или pdfplumber, если use_pdfplumber=True).
      2) Если текст пуст и do_ocr=True => OCR (через tesseract).

    Возвращает объединённый текст (строка).
    """
    if not os.path.isfile(pdf_path):
        logger.warning(f"PDF file not found: {pdf_path}")
        return ""

    text_result = ""
    if use_pdfplumber and pdfplumber is not None:
        text_result = try_pdfplumber_extraction(pdf_path)
    else:
        # По умолчанию PyPDF2
        text_result = try_pypdf2_extraction(pdf_path)

    # Проверяем, не пуст ли текст
    if not text_result.strip() and do_ocr:
        logger.info("Text layer is empty => falling back to OCR.")
        text_result = try_ocr_extraction(pdf_path)

    return text_result


def try_pypdf2_extraction(pdf_path: str) -> str:
    """
    Пытается извлечь текст из PDF, используя PyPDF2.
    Возвращает одну большую строку (pages склеены).
    """
    if PyPDF2 is None:
        logger.warning("PyPDF2 is not installed or import failed.")
        return ""

    text_chunks = []
    try:
        with open(pdf_path, "rb") as f:
            reader = PyPDF2.PdfReader(f)
            for page_index, page in enumerate(reader.pages):
                page_text = page.extract_text() or ""
                text_chunks.append(page_text)
    except Exception as e:
        logger.exception(f"Error reading PDF with PyPDF2: {e}")
        return ""
    all_text = "\n".join(text_chunks)
    return all_text


def try_pdfplumber_extraction(pdf_path: str) -> str:
    """
    Пытается извлечь текст с помощью pdfplumber
    (если pdfplumber импортирован).
    """
    if pdfplumber is None:
        logger.warning("pdfplumber not installed; fallback to PyPDF2.")
        return try_pypdf2_extraction(pdf_path)

    text_chunks = []
    try:
        with pdfplumber.open(pdf_path) as pdf:
            for page_index, page in enumerate(pdf.pages):
                page_text = page.extract_text() or ""
                text_chunks.append(page_text)
    except Exception as e:
        logger.exception(f"Error reading PDF with pdfplumber: {e}")
        return ""
    return "\n".join(text_chunks)


def try_ocr_extraction(pdf_path: str) -> str:
    """
    Запускает OCR для каждой страницы PDF, используя:
      1) pdfimages -> извлекаем .png/.ppm
      2) tesseract -> распознаём
    Склеиваем всё в одну строку.

    Требуется: tesseract, pdfimages (poppler-utils)
    """
    # Создаём temp папку
    with tempfile.TemporaryDirectory() as tmpdir:
        base = os.path.join(tmpdir, "page")  # prefix для pdfimages
        # 1) pdfimages -> извлекаем изображения
        #    -png => вывод в png (или ppm)
        cmd_images = ["pdfimages", "-png", pdf_path, base]
        try:
            subprocess.run(cmd_images, check=True,
                           stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        except subprocess.CalledProcessError as e:
            logger.exception(f"pdfimages failed: {e}")
            return ""

        # Сканируем полученные .png
        extracted_texts = []
        # Вычислим, какие файлы создал pdfimages: page-000.png, page-001.png ...
        for filename in sorted(os.listdir(tmpdir)):
            if filename.startswith("page-") and filename.endswith(".png"):
                img_path = os.path.join(tmpdir, filename)
                # 2) tesseract -> OCR
                ocr_text = run_tesseract_ocr(img_path)
                if ocr_text:
                    extracted_texts.append(ocr_text)

        return "\n".join(extracted_texts)


def run_tesseract_ocr(image_path: str) -> str:
    """
    Запускаем tesseract (CLI) на одном изображении.
    Возвращаем распознанный текст (str).
    """
    # Вывод tesseract будет в <tmpfile>.txt
    with tempfile.NamedTemporaryFile(suffix=".txt", delete=False) as tmpout:
        txt_output = tmpout.name
    try:
        # tesseract image.png outputbasename --dpi 300 --psm 3 ...
        base_output = txt_output.rsplit(".", 1)[0]
        cmd_tess = ["tesseract", image_path, base_output, "--dpi", "300"]
        subprocess.run(cmd_tess, check=True,
                       stdout=subprocess.PIPE, stderr=subprocess.PIPE)

        # Прочитаем результат
        with open(txt_output, "r", encoding="utf-8", errors="ignore") as f:
            text = f.read()
        return text
    except subprocess.CalledProcessError as e:
        logger.exception(f"Tesseract OCR failed on {image_path}: {e}")
        return ""
    finally:
        if os.path.exists(txt_output):
            os.remove(txt_output)
