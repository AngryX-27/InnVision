"""
qa_service/logic/restricted_words_checker.py
--------------------------------------------
Модуль, отвечающий за фильтрацию «плохих» слов (restricted/bad words) в тексте.
Содержит:
1) Функции для загрузки «плохих» слов (из env/settings, текстового файла, комбинированный).
2) Функции для обнаружения и замены слов:
   - detect_bad_words(text, bad_words)
   - replace_bad_words(text, bad_words)
3) Высокоуровневые функции:
   - filter_bad_words(text) (просто «очистить»)
   - check_and_replace_bad_words(text) (вернуть очищенный текст + список обнаруженных)
4) Дополнительные расширения (варианты placeholder, fuzzy-режим, возврат позиций замен).
"""

import os
import re
import logging
from typing import List, Tuple, Dict, Any, Optional
from config.settings import get_settings

logger = logging.getLogger(__name__)

# ------------------------------------------------------------------------------
# 1. Загрузка «плохих» слов
# ------------------------------------------------------------------------------


def load_bad_words_from_env() -> List[str]:
    """
    Загружает «плохие» слова из настроек (через Pydantic),
    либо из окружения (если settings.bad_words_list не пуст).

    Возвращает список слов (в нижнем регистре, без дубликатов).

    Пример:
        settings.bad_words_list = ["плохое_слово1", "  плохое_слово2 "]
        => ["плохое_слово1", "плохое_слово2"]
    """
    settings = get_settings()
    # например, ["плохое_слово1", "плохое_слово2"]
    raw_list = settings.bad_words_list
    cleaned = set(w.strip().lower() for w in raw_list if w.strip())
    bad_words = sorted(cleaned)
    logger.debug("Loaded %d bad words from settings/env", len(bad_words))
    return bad_words


def load_bad_words_from_file(filepath: str) -> List[str]:
    """
    Считывает «плохие» слова из текстового файла (один word/шаблон на строку).
    Возвращает список (нижний регистр, без дубликатов).
    Если файл не найден, логирует ошибку и возвращает пустой список.

    Пример формата файла:
        плохое_слово1
        badword2
        # пустые строки игнорируются
    """
    if not os.path.exists(filepath):
        logger.error("Bad words file not found: %s", filepath)
        return []
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            lines = [line.strip().lower() for line in f if line.strip()]
        cleaned = set(lines)
        bad_words = sorted(cleaned)
        logger.debug("Loaded %d bad words from file %s",
                     len(bad_words), filepath)
        return bad_words
    except Exception as e:
        logger.exception("Failed to load bad words from file: %s", e)
        return []


def get_combined_bad_words(file_path: str = "") -> List[str]:
    """
    Пример функции, объединяющей «плохие» слова из ENV и из файла (если file_path указан).
    Возвращает общий уникальный список (отсортированный).

    Пример:
        env_words = ["плохое_слово1"]
        file_words = ["word2", "word3"]
        => ["плохое_слово1", "word2", "word3"]
    """
    env_words = load_bad_words_from_env()
    file_words = load_bad_words_from_file(file_path) if file_path else []
    combined = set(env_words + file_words)
    result = sorted(combined)
    logger.info("Combined total bad words count = %d", len(result))
    return result


# ------------------------------------------------------------------------------
# 2. Обнаружение/замена «плохих» слов в тексте
# ------------------------------------------------------------------------------

def detect_bad_words(text: str, bad_words: List[str]) -> List[str]:
    """
    Проверяет, какие из bad_words присутствуют в тексте (игнорируя регистр).
    Возвращает список найденных слов (в том виде, как они перечислены в bad_words),
    если найдено совпадение по \bслово\b.

    Пример:
        text = "Это плохое_слово1 пример"
        bad_words = ["плохое_слово1", "другое_слово"]
        => ["плохое_слово1"]
    """
    found = []
    text_lower = text.lower()
    for bw in bad_words:
        pattern = re.compile(rf"\b{re.escape(bw)}\b", re.IGNORECASE)
        if pattern.search(text_lower):
            found.append(bw)
    return found


def replace_bad_words(
    text: str,
    bad_words: List[str],
    placeholder: str = "***",
    fuzzy: bool = False
) -> str:
    """
    Заменяет все вхождения слов из bad_words на placeholder (по умолчанию '***').

    Параметры:
     - text: исходный текст
     - bad_words: список слов (строгое сопоставление)
     - placeholder: строка, которой заменяем (по умолч. '***')
     - fuzzy: если True, используем более «мягкий» поиск 
       (не только \bслово\b, но и в составе слов). 
       По умолчанию False.

    Пример:
        text = "Это плохое_слово1 пример"
        bad_words = ["плохое_слово1"]
        => "Это *** пример"

    Если fuzzy=True, то "плохое" найдётся в "плохое_слово1" 
    даже если нет границы слова:
        pattern = re.compile(re.escape(bw), re.IGNORECASE)
    иначе:
        pattern = re.compile(rf"\b{re.escape(bw)}\b", re.IGNORECASE)
    """
    filtered_text = text
    for bw in bad_words:
        if fuzzy:
            pattern = re.compile(re.escape(bw), re.IGNORECASE)
        else:
            pattern = re.compile(rf"\b{re.escape(bw)}\b", re.IGNORECASE)
        filtered_text = pattern.sub(placeholder, filtered_text)
    return filtered_text


def replace_bad_words_positions(
    text: str,
    bad_words: List[str],
    placeholder: str = "***",
    fuzzy: bool = False
) -> Dict[str, Any]:
    """
    Аналог replace_bad_words, но возвращает словарь:
      {
        "filtered_text": str,
        "positions": List[Tuple[int, int, str]]  # (start, end, matched_word)
      }
    где positions — это список позиций, в которых была произведена замена, 
    вместе с исходным словом.

    Полезно, если нужно подсветить в интерфейсе, где были «запрещённые слова».
    """
    filtered_text = text
    positions = []

    for bw in bad_words:
        if fuzzy:
            pattern = re.compile(re.escape(bw), re.IGNORECASE)
        else:
            pattern = re.compile(rf"\b{re.escape(bw)}\b", re.IGNORECASE)

        # iter find - найдём все вхождения
        for match_obj in pattern.finditer(filtered_text):
            start, end = match_obj.span()
            matched_str = match_obj.group(0)
            positions.append((start, end, matched_str))

        # После определения позиций заменим
        filtered_text = pattern.sub(placeholder, filtered_text)

    return {"filtered_text": filtered_text, "positions": positions}


# ------------------------------------------------------------------------------
# 3. «Высокоуровневые» функции
# ------------------------------------------------------------------------------

def filter_bad_words(
    text: str,
    file_path: str = "",
    placeholder: str = "***",
    fuzzy: bool = False
) -> str:
    """
    Высокоуровневая функция:
      1) Загружает «плохие» слова (из ENV и опционально из файла)
      2) Заменяет их (replace_bad_words) на placeholder
      3) Позволяет включить fuzzy-режим

    :param text: исходный текст
    :param file_path: путь к файлу со словами (если пусто, только ENV)
    :param placeholder: строка-замена (по умолчанию '***')
    :param fuzzy: bool - если True, ищем совпадения без \b

    :return: «очищенный» текст
    """
    bad_words = get_combined_bad_words(file_path)
    filtered_text = replace_bad_words(
        text, bad_words, placeholder=placeholder, fuzzy=fuzzy)
    return filtered_text


def check_and_replace_bad_words(
    text: str,
    file_path: str = "",
    placeholder: str = "***",
    fuzzy: bool = False
) -> Tuple[str, List[str]]:
    """
    Высокоуровневая функция:
      1) Загружает «плохие» слова (ENV + файл)
      2) Вызывает detect_bad_words -> список обнаруженных
      3) Вызывает replace_bad_words -> заменяет их на placeholder
      4) Возвращает (filtered_text, found_list)

    :param text: исходный текст
    :param file_path: путь к файлу со словами
    :param placeholder: строка-замена
    :param fuzzy: bool - если True, поиск идёт даже в составе слов, без границ

    :return: (filtered_text, found_list) 
       где found_list — список тех bad_words, что были найдены
    """
    bad_words = get_combined_bad_words(file_path)
    found_list = detect_bad_words(text, bad_words) if not fuzzy else [
    ]  # fuzzy detect? optional
    filtered_text = replace_bad_words(
        text, bad_words, placeholder=placeholder, fuzzy=fuzzy)
    return (filtered_text, found_list)


def check_and_replace_bad_words_positions(
    text: str,
    file_path: str = "",
    placeholder: str = "***",
    fuzzy: bool = False
) -> Dict[str, Any]:
    """
    Расширенная версия, возвращающая структуру вида:
      {
        "filtered_text": str,
        "positions": List[Tuple[int, int, str]],
        "found_list": List[str]
      }
    где 'positions' указывает, где именно были заменённые сегменты (start, end, matched).
    'found_list' — список всех 'bad_words', что встретились.

    Полезно, если нужно отобразить в интерфейсе подсветку.

    Пример использования:
        result = check_and_replace_bad_words_positions("Hello badword!", placeholder="###", fuzzy=False)
        => {
             "filtered_text": "Hello ###!",
             "positions": [(6, 13, "badword")],
             "found_list": ["badword"]
           }
    """
    bad_words = get_combined_bad_words(file_path)

    # Если fuzzy=False, можем собрать found_list через detect_bad_words
    # Иначе нужно отдельно реализовать fuzzy-поиск. Ниже — упрощённый вариант.
    found_list = detect_bad_words(text, bad_words) if not fuzzy else []

    replace_info = replace_bad_words_positions(
        text, bad_words, placeholder=placeholder, fuzzy=fuzzy)
    return {
        "filtered_text": replace_info["filtered_text"],
        "positions": replace_info["positions"],
        "found_list": found_list
    }
