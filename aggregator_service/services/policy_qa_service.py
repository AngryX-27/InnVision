"""
policy_qa_service.py

Базовый пример продвинутой структуры для проверки текста на соответствие политике/правилам.
Реализует:
  - PolicyQAService: основной сервис проверки
  - Множество "правил" (banned words, regex, allowed contexts и т. п.)
  - Опциональную загрузку правил из конфигурации
  - Сбор детальной информации о нарушениях
  - Логгирование (пример со structlog)

Автор: (Ваша команда/имя)
"""

import os
import re
from typing import List, Dict, Any, Optional
import structlog

# Если structlog не инициализирован глобально, делаем базовую настройку для примера.
structlog.configure(
    processors=[
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.dev.ConsoleRenderer()
    ],
    wrapper_class=structlog.make_filtering_bound_logger(min_level="INFO"),
    context_class=dict,
    cache_logger_on_first_use=True,
)
logger = structlog.get_logger(__name__)

###############################################################################
# Пример "базы" правил: хардкод + потенциальное чтение из JSON/YAML
###############################################################################
DEFAULT_POLICY_RULES = {
    "strict": {
        "banned_words": [
            "terribleword",
            "forbidden",
            "secretstuff"
        ],
        "banned_regex": [
            r"\bdrugs?\b",
            r"\bgamble(r|s)?\b"
        ],
        "allowed_contexts": [
            # допустим, некоторые слова разрешены в "medical" контексте (псевдопример)
        ]
    },
    "medium": {
        "banned_words": [
            "secretstuff"  # менее жёсткий список
        ],
        "banned_regex": [
            r"\bdrugs?\b"
        ],
        "allowed_contexts": []
    }
}


###############################################################################
# Пример Rule-валидаторов
###############################################################################
class BaseRuleChecker:
    """
    Базовый класс для всех «правил»,
    у каждого есть метод `check(text, context, level) -> List[Dict]`.
    Возвращает список «нарушений» (или пустой список).
    """

    def check(self, text: str, context: Optional[str], level: str) -> List[Dict[str, Any]]:
        raise NotImplementedError("Must implement in subclass.")


class BannedWordsChecker(BaseRuleChecker):
    """
    Проверка на «запрещённые слова».
    Хранение слов может быть в памяти (из конфига).
    """

    def __init__(self, policy_rules: Dict[str, Any]):
        # policy_rules: словарь вида { "strict": {...}, "medium": {...} }
        self.policy_rules = policy_rules

    def check(self, text: str, context: Optional[str], level: str) -> List[Dict[str, Any]]:
        """
        Ищем простым способом слова из policy_rules[level]["banned_words"] в тексте.
        Регистрозависимость/независимость — на усмотрение; тут делаем insensitive.
        """
        if level not in self.policy_rules:
            return []

        banned_words = self.policy_rules[level].get("banned_words", [])
        violations = []
        text_lower = text.lower()

        for word in banned_words:
            if word.lower() in text_lower:
                # соберём инфу о нарушении
                start_index = text_lower.find(word.lower())
                end_index = start_index + len(word)
                snippet = text[start_index:end_index]  # кусок исходного текста
                violations.append({
                    "rule": "banned_word",
                    "value": word,
                    "snippet": snippet,
                    "index_range": (start_index, end_index)
                })

        return violations


class BannedRegexChecker(BaseRuleChecker):
    """
    Проверка на «запрещённые шаблоны» (Regex).
    """

    def __init__(self, policy_rules: Dict[str, Any]):
        self.policy_rules = policy_rules

    def check(self, text: str, context: Optional[str], level: str) -> List[Dict[str, Any]]:
        if level not in self.policy_rules:
            return []

        banned_patterns = self.policy_rules[level].get("banned_regex", [])
        violations = []

        for pattern in banned_patterns:
            regex = re.compile(pattern, flags=re.IGNORECASE)
            for match in regex.finditer(text):
                snippet = match.group(0)
                start_index, end_index = match.span()
                violations.append({
                    "rule": "banned_regex",
                    "pattern": pattern,
                    "snippet": snippet,
                    "index_range": (start_index, end_index)
                })

        return violations


###############################################################################
# Основной сервис PolicyQAService
###############################################################################
class PolicyQAService:
    """
    Сервис, координирующий проверку контента на соответствие политике.
    Поддерживает:
      - Разные уровни политики ("strict", "medium" ...).
      - Набор чекеров (banned words, regex, etc.).
      - Возможность расширять логику (allowed contexts, thresholds).
      - Логгирование с помощью structlog.
    """

    def __init__(
        self,
        policy_rules: Optional[Dict[str, Any]] = None,
        default_level: str = "strict"
    ):
        """
        :param policy_rules: Словарь с описанием правил, если None — используем DEFAULT_POLICY_RULES.
        :param default_level: Уровень жёсткости политики по умолчанию.
        """
        self.logger = logger.bind(service="PolicyQAService")
        if policy_rules is None:
            self.policy_rules = DEFAULT_POLICY_RULES
        else:
            self.policy_rules = policy_rules

        self.default_level = default_level

        # Регистрируем чекеры
        # При желании можно реализовать plug-in систему:
        self.checkers: List[BaseRuleChecker] = [
            BannedWordsChecker(self.policy_rules),
            BannedRegexChecker(self.policy_rules)
            # -> сюда можно добавить и другие проверки: offensiveLanguageChecker, ...
        ]

    def check_text(
        self,
        text: str,
        context: Optional[str] = None,
        level: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Основной метод для проверки текста на нарушения.
        :param text: Строка текста для проверки.
        :param context: Доп. информация (тип документа, категория, язык).
        :param level: Уровень политики (strict, medium и т. д.). Если не указано, используем default.
        :return: Структура:
            {
              "passed": bool,  # True, если нет нарушений
              "violations": [ { "rule":"...", ... } ],
              "level": str,
              "details": "...",
              ...
            }
        """
        policy_level = level or self.default_level

        self.logger.info(
            "check_text_started",
            text_preview=text[:50],
            level=policy_level,
            context=context
        )

        all_violations = []
        for checker in self.checkers:
            try:
                result = checker.check(text, context, policy_level)
                if result:
                    all_violations.extend(result)
            except Exception as ex:
                self.logger.error(
                    "checker_error",
                    checker_type=str(checker.__class__.__name__),
                    error=str(ex)
                )

        # Формируем итог
        passed = len(all_violations) == 0
        result = {
            "passed": passed,
            "violations": all_violations,
            "level": policy_level,
            "context": context
        }

        if not passed:
            self.logger.warning(
                "check_text_violations",
                count=len(all_violations),
                level=policy_level
            )
        else:
            self.logger.info(
                "check_text_ok",
                level=policy_level
            )

        return result

    def load_rules_from_file(self, filepath: str) -> None:
        """
        Пример метода, который может читать внешние правила из JSON/YAML-файла (зависит от формата).
        Для простоты здесь заглушка.
        """
        self.logger.info("load_rules_from_file", filepath=filepath)
        # Пример: если JSON:
        # import json
        # with open(filepath, 'r', encoding='utf-8') as f:
        #     data = json.load(f)
        # self.policy_rules = data
        # Или YAML:
        # import yaml
        # with open(filepath, 'r', encoding='utf-8') as f:
        #     data = yaml.safe_load(f)
        # self.policy_rules = data

        pass  # пока не реализовано, но структура позволяет легко добавить


###############################################################################
# Пример использования (при запуске файла напрямую)
###############################################################################
if __name__ == "__main__":
    service = PolicyQAService()
    test_text = "Here we talk about secretstuff and also some DRUGS. It's forbidden, right?"
    check_result = service.check_text(
        test_text, context="test_run", level="strict")

    print("RESULT:", check_result)
    # Пример вывода:
    # {
    #   "passed": False,
    #   "violations": [
    #       {"rule": "banned_word", "value": "secretstuff", "snippet": "secretstuff", ...},
    #       {"rule": "banned_regex", "pattern": "\\bdrugs?\\b", "snippet": "DRUGS", ...},
    #       {"rule": "banned_word", "value": "forbidden", "snippet": "forbidden", ...}
    #   ],
    #   "level": "strict",
    #   "context": "test_run"
    # }
