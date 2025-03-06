"""
qa_service/services/language_tool_client.py
-------------------------------------------
Расширенный клиент для LanguageTool (language_tool_python).

Возможности:
 - Гибкая инициализация (set_language, initialize_tool).
 - Методы проверки текста (check_text), автокоррекции (correct_text).
 - Игнорирование/включение правил (disable_rules, enable_rules, reset_rules).
 - Персональный словарь (add_to_dict).
 - Возможность хранить "persistent" набор правил, которые всегда отключены,
   и "persistent" словарь слов, которые всегда считаются допустимыми.

Пример использования:
    client = LanguageToolClient(language_code="ru")
    client.add_to_persistent_dict(["QAService", "InnVision"])
    client.disable_persistent_rules(["WHITESPACE_RULE", "RU_NUMBER_RULE"])

    result = client.check_text(
        text="Пример тескта",
        auto_correct=True,
        ignore_rules=["SOME_TMP_RULE"],
        personal_dict=["MyProject123"]
    )
    print(result)
    # {
    #   "found_issues": [...],
    #   "warnings": [...],
    #   "corrected_text": "...",
    # }

"""

import logging
from typing import List, Dict, Any, Optional

import language_tool_python

logger = logging.getLogger(__name__)


class LanguageToolClient:
    """
    Обёртка вокруг language_tool_python.LanguageTool, позволяющая гибко
    управлять языком, автокоррекцией, правилами и словарём (персональным и временным).

    Основные поля:
     - language_code: текущий код языка (например, "ru" или "en-US").
     - persistent_disabled_rules: список правил, которые всегда отключены.
     - persistent_dict_words: список слов, которые всегда считаются допустимыми.
     - _tool: объект LanguageTool (или None, если инициализация не удалась).
     - _initialized: флаг, говорящий, что _tool успешно инициализирован.

    Методы для проверки:
     - check_text(...) : возвращает {found_issues, warnings, corrected_text}
    """

    def __init__(
        self,
        language_code: str = "en-US",
        initialize: bool = True
    ):
        """
        :param language_code: Код языка (e.g. "ru", "en-US", "de-DE").
        :param initialize: Если True, сразу инициализируем LanguageTool.
        """
        self.language_code = language_code
        self._tool: Optional[language_tool_python.LanguageTool] = None
        self._initialized = False

        # "Persistent" правила, которые будут всегда отключены
        self.persistent_disabled_rules: List[str] = []
        # "Persistent" слова, которые считаем корректными
        self.persistent_dict_words: List[str] = []

        if initialize:
            self.initialize_tool()

    # --------------------------------------------------------------------------
    # ИНИЦИАЛИЗАЦИЯ И СМЕНА ЯЗЫКА
    # --------------------------------------------------------------------------
    def initialize_tool(self) -> None:
        """
        Инициализирует self._tool, используя self.language_code.
        Если _tool уже инициализирован, ничего не делаем.
        """
        if self._initialized:
            logger.debug(
                "LanguageTool уже инициализирован (lang=%s).", self.language_code)
            return

        try:
            self._tool = language_tool_python.LanguageTool(self.language_code)
            self._initialized = True
            logger.info(
                "LanguageToolClient инициализирован (lang=%s).", self.language_code)

            # Применяем "persistent" правила и слова
            self._apply_persistent_rules_and_dict()

        except Exception as e:
            logger.exception(
                "Не удалось инициализировать LanguageTool (lang=%s): %s", self.language_code, e)
            self._tool = None

    def set_language(self, new_language_code: str) -> None:
        """
        Меняет язык клиента и переинициализирует инструмент.
        Полезно, если нужно в рамках одного клиента переключиться с en-US на ru и т.д.
        """
        if new_language_code == self.language_code and self._initialized:
            logger.debug(
                "set_language(%s): уже установлен этот язык, пропускаем.", new_language_code)
            return

        logger.info("Смена языка с %s на %s, переинициализация LT.",
                    self.language_code, new_language_code)
        self.language_code = new_language_code
        self._tool = None
        self._initialized = False
        self.initialize_tool()

    def _apply_persistent_rules_and_dict(self) -> None:
        """
        Применяет "persistent_disabled_rules" и "persistent_dict_words"
        к текущему self._tool. Вызывается после инициализации.
        """
        if not self._tool:
            return
        if self.persistent_disabled_rules:
            existing = set(self._tool.disabled_rules)
            new_set = existing | set(self.persistent_disabled_rules)
            self._tool.disabled_rules = list(new_set)
            logger.debug("Применили persistent_disabled_rules (%d)",
                         len(self.persistent_disabled_rules))

        if self.persistent_dict_words:
            for w in self.persistent_dict_words:
                if w.strip():
                    self._tool.add_dictionary_word(w.strip())
            logger.debug("Применили persistent_dict_words (%d)",
                         len(self.persistent_dict_words))

    # --------------------------------------------------------------------------
    # ПЕРСИСТЕНТНЫЕ ОПЦИИ (ПРАВИЛА, СЛОВА)
    # --------------------------------------------------------------------------
    def disable_persistent_rules(self, rules: List[str]) -> None:
        """
        Добавляет правила в общий (перманентно отключённый) список.
        Если инструмент уже инициализирован, сразу применяет их.
        """
        newly_added = 0
        for r in rules:
            if r not in self.persistent_disabled_rules:
                self.persistent_disabled_rules.append(r)
                newly_added += 1

        if newly_added > 0 and self._tool:
            # Применяем
            existing = set(self._tool.disabled_rules)
            new_set = existing | set(rules)
            self._tool.disabled_rules = list(new_set)
            logger.debug("Добавили %d persistent-правил, всего в persistent=%d",
                         newly_added, len(self.persistent_disabled_rules))

    def enable_persistent_rules(self, rules: List[str]) -> None:
        """
        Убирает правила из общего списка "persistent_disabled_rules".
        Если инструмент уже инициализирован, возвращает их в включённое состояние.
        """
        removed = 0
        for r in rules:
            if r in self.persistent_disabled_rules:
                self.persistent_disabled_rules.remove(r)
                removed += 1

        if removed > 0 and self._tool:
            # Применяем
            # Оставляем всё, что было, кроме возвращённых
            current_disabled = set(self._tool.disabled_rules)
            for r in rules:
                if r in current_disabled:
                    current_disabled.remove(r)
            self._tool.disabled_rules = list(current_disabled)
            logger.debug("Убрали %d правил из persistent-списка, всего в persistent=%d",
                         removed, len(self.persistent_disabled_rules))

    def reset_rules(self) -> None:
        """
        Очищает persistent_disabled_rules (и, если инструмент инициализирован,
        сбрасывает self._tool.disabled_rules в пустой список).
        """
        count = len(self.persistent_disabled_rules)
        self.persistent_disabled_rules.clear()

        if self._tool:
            self._tool.disabled_rules = []
        logger.debug(
            "reset_rules(): очищены все persistent-правила (было %d).", count)

    def add_to_persistent_dict(self, words: List[str]) -> None:
        """
        Добавляет слова в общий persistent-словарь. Если инструмент инициализирован,
        сразу применяет их (self._tool.add_dictionary_word).
        """
        newly_added = 0
        for w in words:
            w_stripped = w.strip()
            if w_stripped and w_stripped not in self.persistent_dict_words:
                self.persistent_dict_words.append(w_stripped)
                newly_added += 1

        if newly_added > 0 and self._tool:
            for w in words:
                w_stripped = w.strip()
                if w_stripped:
                    self._tool.add_dictionary_word(w_stripped)
            logger.debug("add_to_persistent_dict: Добавили %d слов. Всего=%d",
                         newly_added, len(self.persistent_dict_words))

    def reset_persistent_dict(self) -> None:
        """
        Очищает persistent_dict_words. Не может «удалить» слова из уже инициализированного
        self._tool, т.к. библиотека language_tool_python не поддерживает remove_dictionary_word.
        Но все новые проверки слов уже не будут добавляться.
        """
        count = len(self.persistent_dict_words)
        self.persistent_dict_words.clear()
        logger.debug(
            "reset_persistent_dict(): убрано %d слов из persistent-списка.", count)

    # --------------------------------------------------------------------------
    # МЕТОДЫ УПРАВЛЕНИЯ ПРАВИЛАМИ (ВРЕМЕННО, НА ВРЕМЯ ОДНОГО ЗАПРОСА)
    # --------------------------------------------------------------------------
    def disable_rules(self, rules: List[str]) -> None:
        """
        Отключает указанные правила ТОЛЬКО на текущее время (меняя self._tool.disabled_rules).
        После следующего check_text, если вы сделаете reset или 
        переинициализацию, они могут вернуться.  
        Если нужно отключить навсегда, используйте disable_persistent_rules.
        """
        if not self._tool:
            logger.warning(
                "disable_rules: инструмент не инициализирован, пропускаем.")
            return
        current = set(self._tool.disabled_rules)
        new = current | set(rules)
        self._tool.disabled_rules = list(new)
        logger.debug("Временное отключение %d правил, всего %d сейчас.", len(
            rules), len(self._tool.disabled_rules))

    def enable_rules(self, rules: List[str]) -> None:
        """
        Включает указанные правила обратно (если они были отключены только временно).
        Если они были в persistent_disabled_rules, их нужно убирать там отдельно.
        """
        if not self._tool:
            logger.warning(
                "enable_rules: инструмент не инициализирован, пропускаем.")
            return
        current = set(self._tool.disabled_rules)
        removed = 0
        for r in rules:
            if r in current:
                current.remove(r)
                removed += 1
        self._tool.disabled_rules = list(current)
        logger.debug("enable_rules(): убрали %d правил из disabled.", removed)

    # --------------------------------------------------------------------------
    # МЕТОДЫ ПРОВЕРКИ И АВТОКОРРЕКЦИИ
    # --------------------------------------------------------------------------
    def check_text(
        self,
        text: str,
        auto_correct: bool = False,
        ignore_rules: Optional[List[str]] = None,
        personal_dict: Optional[List[str]] = None
    ) -> Dict[str, Any]:
        """
        Проверка текста через LanguageTool (self._tool).

        :param text: Исходный текст
        :param auto_correct: True => делаем автокоррекцию
        :param ignore_rules: ВРЕМЕННО отключаемые правила, кроме persistent
        :param personal_dict: временные «белые» слова, кроме persistent

        :return:
          {
            "found_issues": [ { "offset", "error_text", "suggestions" }, ...],
            "warnings": [...],
            "corrected_text": <str|None>
          }
        """
        warnings = []
        found_issues = []
        corrected_text = None

        if not self._initialized or not self._tool:
            logger.warning(
                "LanguageToolClient: инструмент не инициализирован.")
            return {
                "found_issues": [],
                "warnings": ["LanguageTool not initialized"],
                "corrected_text": None
            }

        # Сохраним текущий список disabled_rules, потом вернём
        original_rules = list(self._tool.disabled_rules)

        try:
            # Если есть ignore_rules, отключим их на время
            if ignore_rules:
                self.disable_rules(ignore_rules)

            # Если есть personal_dict, добавим его (без возврата)
            tmp_added_words = []
            if personal_dict:
                for w in personal_dict:
                    w_s = w.strip()
                    if w_s:
                        self._tool.add_dictionary_word(w_s)
                        tmp_added_words.append(w_s)

            # Запускаем проверку
            matches = self._tool.check(text)

            for m in matches:
                found_issues.append({
                    "offset": m.offset,
                    "error_text": m.matchedText,
                    "suggestions": m.replacements
                })

            # Если автокоррекция
            if auto_correct:
                from language_tool_python.utils import correct
                try:
                    corrected_text = correct(text, matches)
                except Exception as e:
                    warnings.append(f"Auto-correct failed: {e}")
                    logger.warning("Auto-correct failed: %s", e)

        except Exception as e:
            logger.exception("Ошибка check_text: %s", e)
            warnings.append(str(e))

        finally:
            # Вернём disabled_rules в исходное состояние
            self._tool.disabled_rules = original_rules

            # personal_dict: language_tool_python нет метода удалять слова,
            # так что "tmp_added_words" остаются, но это «временная» особенность.
            # Чтобы «откатить», нужно переинициализировать инструмент заново.

        return {
            "found_issues": found_issues,
            "warnings": warnings,
            "corrected_text": corrected_text
        }

    def correct_text(
        self,
        text: str,
        matches: Optional[List[language_tool_python.Match]] = None
    ) -> str:
        """
        Если уже есть список matches (от .tool.check),
        можно вручную вызвать автокоррекцию.

        :param text: исходный текст
        :param matches: список Match. Если None, заново делаем self._tool.check(text).
        :return: скорректированный текст
        """
        if not self._initialized or not self._tool:
            logger.warning(
                "correct_text: инструмент не инициализирован, возвращаем исходный текст.")
            return text

        if matches is None:
            matches = self._tool.check(text)

        from language_tool_python.utils import correct
        try:
            return correct(text, matches)
        except Exception as e:
            logger.warning("Autocorrect failed in correct_text(): %s", e)
            return text
