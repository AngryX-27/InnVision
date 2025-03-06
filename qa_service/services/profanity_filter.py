"""
qa_service/services/profanity_filter.py
---------------------------------------
Клиент/модуль для фильтрации «плохих» (нецензурных) слов в тексте.

Возможности:
 - Загрузка «плохих» слов из ENV (Pydantic-настроек) + из файла (опционально)
 - "Fuzzy" режим (подстрочная замена) или строгий (\bслово\b)
 - Возврат позиций замен
 - «persistent» настройки внутри класса (placeholder, fuzzy, file_path)
 - Быстрые статические функции (filter_text_once, detect_words_once), если нужна процедура без сохранения state.

Пример:
    filter_client = ProfanityFilterClient(
        placeholder="###", fuzzy=True, file_path="bad_words.txt"
    )
    result = filter_client.filter_text("Hello badword example")
    print(result)  # "Hello ### example"

    # Если нужно отслеживать позиции:
    detail = filter_client.filter_with_positions("This is a badword too.")
    print(detail)
    # {
    #   "filtered_text": "This is a ### too.",
    #   "positions": [(8, 15, "badword")]
    # }

"""

import os
import re
import logging
from typing import List, Tuple, Dict, Any, Optional

from config.settings import get_settings

logger = logging.getLogger(__name__)

# ------------------------------------------------------------------------------
# 1. Утилиты для загрузки/объединения «плохих» слов
# ------------------------------------------------------------------------------


def load_words_from_env() -> List[str]:
    """
    Загружает «плохие» слова из Pydantic-настроек (settings.bad_words_list).
    Возвращает список (в нижнем регистре, без дубликатов).
    """
    settings = get_settings()
    raw = settings.bad_words_list  # ["badword1", "плохое_слово2", ...]
    cleaned = {w.strip().lower() for w in raw if w.strip()}
    words = sorted(cleaned)
    logger.debug("Loaded %d bad words from ENV settings.", len(words))
    return words


def load_words_from_file(filepath: str) -> List[str]:
    """
    Считывает «плохие» слова из текстового файла (по строкам).
    Возвращает список (нижний регистр, без дубликатов).
    """
    if not os.path.exists(filepath):
        logger.warning("File with bad words not found: %s", filepath)
        return []
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            lines = [line.strip().lower() for line in f if line.strip()]
        cleaned = set(lines)
        words = sorted(cleaned)
        logger.debug("Loaded %d bad words from file: %s", len(words), filepath)
        return words
    except Exception as e:
        logger.exception(
            "Error loading bad words from file=%s: %s", filepath, e)
        return []


def combine_bad_words(env_list: List[str], file_list: List[str]) -> List[str]:
    """
    Объединяет два списка (ENV и FILE) в один (уникальный) список.
    """
    combined = set(env_list + file_list)
    result = sorted(combined)
    logger.info("Combined bad words total: %d", len(result))
    return result

# ------------------------------------------------------------------------------
# 2. Функции «одним вызовом» (не обязательно пользоваться классом)
# ------------------------------------------------------------------------------


def detect_words_once(
    text: str,
    fuzzy: bool = False,
    file_path: str = ""
) -> List[str]:
    """
    Выявляет, какие «плохие» слова присутствуют в тексте (игнорируем регистр).
    Возвращает список найденных.

    :param text: исходный текст
    :param fuzzy: True => ищем вхождения без границ (\b). False => \bслово\b
    :param file_path: файл со словами (дополнительно к ENV)
    """
    env_words = load_words_from_env()
    file_words = load_words_from_file(file_path) if file_path else []
    bad_words = combine_bad_words(env_words, file_words)

    found = []
    text_lower = text.lower()

    for bw in bad_words:
        if fuzzy:
            pattern = re.compile(re.escape(bw), re.IGNORECASE)
        else:
            pattern = re.compile(rf"\b{re.escape(bw)}\b", re.IGNORECASE)
        if pattern.search(text_lower):
            found.append(bw)
    return found


def filter_text_once(
    text: str,
    fuzzy: bool = False,
    file_path: str = "",
    placeholder: str = "***"
) -> str:
    """
    Единовременная фильтрация (замена) «плохих» слов.
    :param text: исходный текст
    :param fuzzy: True => ищем подстрочно, False => \bслово\b
    :param file_path: доп. файл
    :param placeholder: замена, default='***'
    """
    env_words = load_words_from_env()
    file_words = load_words_from_file(file_path) if file_path else []
    bad_words = combine_bad_words(env_words, file_words)

    filtered = text
    for bw in bad_words:
        if fuzzy:
            pattern = re.compile(re.escape(bw), re.IGNORECASE)
        else:
            pattern = re.compile(rf"\b{re.escape(bw)}\b", re.IGNORECASE)
        filtered = pattern.sub(placeholder, filtered)
    return filtered


def filter_with_positions_once(
    text: str,
    fuzzy: bool = False,
    file_path: str = "",
    placeholder: str = "***"
) -> Dict[str, Any]:
    """
    Аналог filter_text_once, но возвращает словарь:
      {
        "filtered_text": str,
        "positions": List[(start, end, matched_str)]
      }
    """
    env_words = load_words_from_env()
    file_words = load_words_from_file(file_path) if file_path else []
    bad_words = combine_bad_words(env_words, file_words)

    filtered = text
    positions = []

    for bw in bad_words:
        if fuzzy:
            pattern = re.compile(re.escape(bw), re.IGNORECASE)
        else:
            pattern = re.compile(rf"\b{re.escape(bw)}\b", re.IGNORECASE)

        # найдём все вхождения
        for match_obj in pattern.finditer(filtered):
            start, end = match_obj.span()
            matched_str = match_obj.group(0)
            positions.append((start, end, matched_str))

        # заменим
        filtered = pattern.sub(placeholder, filtered)

    return {
        "filtered_text": filtered,
        "positions": positions
    }

# ------------------------------------------------------------------------------
# 3. Класс ProfanityFilterClient («боевой» клиент)
# ------------------------------------------------------------------------------


class ProfanityFilterClient:
    """
    Класс, который хранит «persistent» настройки (file_path, fuzzy, placeholder) и 
    после инициализации может многократно фильтровать тексты.

    Пример:
        pf_client = ProfanityFilterClient(
            fuzzy=True,
            placeholder="[censored]",
            file_path="bad_words.txt"
        )
        text = "Here is a badword"
        filtered = pf_client.filter_text(text)
        print(filtered)  # "Here is a [censored]"
    """

    def __init__(
        self,
        fuzzy: bool = False,
        placeholder: str = "***",
        file_path: str = ""
    ):
        """
        :param fuzzy: True => искать подстрочно, False => целые слова (\b).
        :param placeholder: чем заменяем плохие слова.
        :param file_path: путь к файлу со словами (доп. к списку ENV)
        """
        self.fuzzy = fuzzy
        self.placeholder = placeholder
        self.file_path = file_path

        # "Кэш" списка bad_words (ENV + FILE)
        self.bad_words_cache: List[str] = []
        self._loaded = False

    def load_words(self) -> None:
        """
        Загружает и кэширует bad_words из ENV + file_path (если указан).
        """
        env_list = load_words_from_env()
        file_list = load_words_from_file(
            self.file_path) if self.file_path else []
        self.bad_words_cache = combine_bad_words(env_list, file_list)
        self._loaded = True
        logger.debug("ProfanityFilterClient: loaded %d bad words (fuzzy=%s).", len(
            self.bad_words_cache), self.fuzzy)

    def ensure_loaded(self) -> None:
        """
        Проверяет, загружены ли слова. Если нет, вызывает load_words().
        """
        if not self._loaded:
            self.load_words()

    def detect_words(self, text: str) -> List[str]:
        """
        Список bad_words (из кэша), которые реально присутствуют в тексте.
        """
        self.ensure_loaded()
        found = []
        text_lower = text.lower()

        for bw in self.bad_words_cache:
            if self.fuzzy:
                pattern = re.compile(re.escape(bw), re.IGNORECASE)
            else:
                pattern = re.compile(rf"\b{re.escape(bw)}\b", re.IGNORECASE)
            if pattern.search(text_lower):
                found.append(bw)
        return found

    def filter_text(self, text: str) -> str:
        """
        Фильтрует (заменяет) bad_words, возвращает отфильтрованный текст.
        """
        self.ensure_loaded()
        filtered = text
        for bw in self.bad_words_cache:
            if self.fuzzy:
                pattern = re.compile(re.escape(bw), re.IGNORECASE)
            else:
                pattern = re.compile(rf"\b{re.escape(bw)}\b", re.IGNORECASE)
            filtered = pattern.sub(self.placeholder, filtered)
        return filtered

    def filter_with_positions(self, text: str) -> Dict[str, Any]:
        """
        Фильтрует bad_words, возвращая:
          {
            "filtered_text": <...>,
            "positions": [ (start, end, matched_str), ...]
          }
        """
        self.ensure_loaded()
        filtered = text
        positions = []

        for bw in self.bad_words_cache:
            if self.fuzzy:
                pattern = re.compile(re.escape(bw), re.IGNORECASE)
            else:
                pattern = re.compile(rf"\b{re.escape(bw)}\b", re.IGNORECASE)

            # Сначала найдём все вхождения
            for match_obj in pattern.finditer(filtered):
                start, end = match_obj.span()
                matched_str = match_obj.group(0)
                positions.append((start, end, matched_str))

            # Потом заменяем
            filtered = pattern.sub(self.placeholder, filtered)

        return {
            "filtered_text": filtered,
            "positions": positions
        }

    def reload_words(self) -> None:
        """
        Сбрасывает флаг _loaded и загружает заново (полезно, если изменился файл).
        """
        self._loaded = False
        self.load_words()
