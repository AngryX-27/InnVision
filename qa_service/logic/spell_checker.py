"""
qa_service/logic/spell_checker.py
---------------------------------
Модуль для орфографической/грамматической проверки текста,
используя LanguageTool (language_tool_python) с учётом:
 - автокоррекции (опционально)
 - персонального словаря (optional)
 - списков игнорируемых правил
 - чтения языка (LANGUAGE_CODE) из Pydantic-настроек

Основная функция:
    run_spell_check(text, auto_correct=False, ignore_rules=None, personal_dict=None)

Формат ответа:
    {
      "found_issues": [
         {
           "offset": int,
           "error_text": str,
           "suggestions": List[str]
         }, ...
      ],
      "warnings": List[str],
      "corrected_text": Optional[str]
    }
"""

import logging
from typing import Dict, Any, List, Optional

import language_tool_python
from config.settings import get_settings

logger = logging.getLogger(__name__)

# ------------------------------------------------------------------------------
# 1. Инициализация инструмента LanguageTool
# ------------------------------------------------------------------------------
# Опционально: Можно сделать ленивую инициализацию через get_tool().
# Здесь — для примера сразу создаём при импортировании модуля.

try:
    _settings = get_settings()
    DEFAULT_LANGUAGE = _settings.QA_SERVICE_LANG  # например, "ru" или "en-US"
except Exception as e:
    logger.exception("Ошибка при загрузке настроек: %s", e)
    DEFAULT_LANGUAGE = "en-US"  # fallback, если нет настроек

try:
    # Создаём дефолтный инструмент (можно будет перенастроить)
    tool = language_tool_python.LanguageTool(DEFAULT_LANGUAGE)
    logger.info(
        "LanguageTool инициализирован (язык по умолчанию: %s).", DEFAULT_LANGUAGE)
except Exception as e:
    logger.error("Не удалось инициализировать LanguageTool: %s", e)
    tool = None


# ------------------------------------------------------------------------------
# 2. Вспомогательная функция для добавления персонального словаря
# ------------------------------------------------------------------------------
def add_personal_dictionary(tool_instance: language_tool_python.LanguageTool, words: List[str]) -> None:
    """
    Добавляет персональный список слов «words» в инструмент LanguageTool,
    чтобы они не считались ошибками.
    Пример: add_personal_dictionary(tool, ["QAService", "InnVision", "microservices"])

    :param tool_instance: Экземпляр LanguageTool
    :param words: Список слов, которые нужно добавить в «Whitelist».
    """
    if not tool_instance:
        logger.warning(
            "LanguageTool не инициализирован, пропускаем add_personal_dictionary.")
        return
    for w in words:
        w_stripped = w.strip()
        if w_stripped:
            tool_instance.add_dictionary_word(w_stripped)
    logger.debug(
        "Добавлено %d слов в персональный словарь LanguageTool", len(words))


# ------------------------------------------------------------------------------
# 3. Игнорируемые правила
# ------------------------------------------------------------------------------
def disable_rules(tool_instance: language_tool_python.LanguageTool, rules: List[str]) -> None:
    """
    Отключает указанные правила в LanguageTool.
    Пример: disable_rules(tool, ["WHITESPACE_RULE", "EN_QUOTES"])
    """
    if not tool_instance:
        logger.warning(
            "LanguageTool не инициализирован, пропускаем disable_rules.")
        return

    # Для отключения правил LanguageTool в python есть метод .disabled_rules
    # Можно напрямую присвоить список:
    # tool.disabled_rules = ["RULE_1", "RULE_2", ...]
    existing = tool_instance.disabled_rules
    new_set = set(existing) | set(rules)
    tool_instance.disabled_rules = list(new_set)
    logger.debug("Отключили %d правил в LanguageTool, всего отключено: %d",
                 len(rules), len(tool_instance.disabled_rules))


# ------------------------------------------------------------------------------
# 4. Основная функция run_spell_check
# ------------------------------------------------------------------------------
def run_spell_check(
    text: str,
    auto_correct: bool = False,
    language_code: Optional[str] = None,
    ignore_rules: Optional[List[str]] = None,
    personal_dict: Optional[List[str]] = None
) -> Dict[str, Any]:
    """
    Выполняет орфографическую/грамматическую проверку с помощью LanguageTool.

    :param text: Исходный текст
    :param auto_correct: Нужно ли выполнять автокоррекцию
    :param language_code: Код языка (e.g. "ru", "en-US"); если не указано, берём DEFAULT_LANGUAGE
    :param ignore_rules: Список ID правил, которые нужно отключить (e.g. ["WHITESPACE_RULE"])
    :param personal_dict: Список слов, которые считаем «разрешёнными» (добавляем в словарь)

    :return: Словарь формата:
        {
          "found_issues": [
             {"offset": int, "error_text": str, "suggestions": [str, ...]}, ...
          ],
          "warnings": [str, ...],
          "corrected_text": Optional[str]
        }
    """
    warnings = []
    found_issues = []
    corrected_text = None

    if not tool:
        # Если не удалось инициализировать LanguageTool при импорте
        # или произошла ошибка, мы возвращаем предупреждение
        logger.warning(
            "LanguageTool недоступен (tool=None). Проверка не выполнена.")
        return {
            "found_issues": found_issues,
            "warnings": ["LanguageTool not initialized"],
            "corrected_text": corrected_text
        }

    # Если пользователь хочет другой язык, пытаемся создать новый экземпляр
    # (или переинициализировать). Иначе используем global tool.
    if language_code and language_code != DEFAULT_LANGUAGE:
        logger.debug(
            "Инициализируем LanguageTool для языка: %s", language_code)
        try:
            local_tool = language_tool_python.LanguageTool(language_code)
        except Exception as e:
            logger.exception(
                "Не удалось инициализировать LanguageTool для %s", language_code)
            # fallback - глобальный tool
            local_tool = tool
            warnings.append(
                f"Fail init LanguageTool for {language_code}, fallback to {DEFAULT_LANGUAGE}")
    else:
        local_tool = tool

    # Игнорируемые правила
    if ignore_rules:
        disable_rules(local_tool, ignore_rules)

    # Персональный словарь
    if personal_dict:
        add_personal_dictionary(local_tool, personal_dict)

    # Выполняем проверку
    try:
        matches = local_tool.check(text)
        for m in matches:
            found_issues.append({
                "offset": m.offset,
                "error_text": m.matchedText,
                "suggestions": m.replacements
            })

        if auto_correct:
            from language_tool_python.utils import correct
            try:
                corrected_text = correct(text, matches)
            except Exception as e:
                logger.warning("Автокоррекция не удалась: %s", e)
                warnings.append(f"Auto-correct failed: {e}")

    except Exception as e:
        logger.exception("Ошибка при выполнении LanguageTool check: %s", e)
        warnings.append(str(e))

    # Восстанавливаем настройки инструмента (отключённые правила, словари),
    # если нужно «чистить» после разовой проверки. В данном примере не очищаем —
    # пусть остаётся.

    logger.debug("run_spell_check completed: found_issues=%d, auto_correct=%s", len(
        found_issues), auto_correct)
    return {
        "found_issues": found_issues,
        "warnings": warnings,
        "corrected_text": corrected_text
    }


# ------------------------------------------------------------------------------
# 5. Примеры использования (локальные тесты)
# ------------------------------------------------------------------------------
if __name__ == "__main__":
    # Пример: локальный тест модуля
    sample_text = "Это пример текста, которий содерсжит некторые ошибки. QAServic is awsome."
    logger.info("Testing run_spell_check on sample_text...")

    result = run_spell_check(
        text=sample_text,
        auto_correct=True,
        language_code="ru",          # Предположим, проверяем на русском
        ignore_rules=["WHITESPACE_RULE"],
        personal_dict=["QAServic", "InnVision"]  # допустимые слова
    )
    logger.info("Result: %s", result)
