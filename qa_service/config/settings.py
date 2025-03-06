"""
qa_service/config/settings.py
-----------------------------
Хранит все настройки (конфигурацию) для QA-сервиса, используя Pydantic
для чтения и валидации переменных окружения (или .env).

Новые поля (LOG_CONSOLE_LEVEL, LOG_FILE_LEVEL, etc.) 
призваны расширить гибкость логирования, если вы используете logging_config.py 
с раздельными уровнями логирования для консоли и файла.
"""

import os
from typing import List, Optional

try:
    # Если хотите подхватывать локальный .env при разработке,
    # а не только переменные окружения из системы/docker,
    # подключите это:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

from pydantic_settings import BaseSettings
from pydantic import Field


class Settings(BaseSettings):
    """Класс для всех ключевых настроек нашего QA-сервиса."""

    # =====================
    # Основные настройки приложения
    # =====================
    QA_SERVICE_PORT: int = Field(
        5003,
        description="Порт, на котором работает QA-сервис"
    )
    QA_SERVICE_DEBUG: bool = Field(
        True,
        description="Режим отладки Flask"
    )
    QA_SERVICE_LANG: str = Field(
        "ru",
        description="Язык, используемый LanguageTool (ru, en-US и т.д.)"
    )

    # Запрещённые слова; по умолчанию — несколько примеров
    QA_SERVICE_BAD_WORDS: str = Field(
        "плохое_слово1;плохое_слово2",
        description="Строка со списком 'плохих' слов, разделённых точкой с запятой"
    )

    # Автокоррекция (true/false)
    QA_SERVICE_AUTO_CORRECT: bool = Field(
        False,
        description="Включать ли автоматическую коррекцию текста?"
    )

    # =====================
    # Логирование (базовые)
    # =====================
    LOG_LEVEL: str = Field(
        "INFO",
        description="Уровень логирования (DEBUG/INFO/WARNING/ERROR/CRITICAL)"
    )
    ENABLE_JSON_LOGS: bool = Field(
        False,
        description="Включить ли JSON-логирование?"
    )
    LOG_FILE: str = Field(
        "",
        description="Путь к файлу логов (если пусто - вывод только в консоль)"
    )

    # =====================
    # Логирование (расширенные опции)
    # =====================
    LOG_CONSOLE_LEVEL: str = Field(
        None,
        description="Уровень логирования для консоли (если не указан, используется LOG_LEVEL)."
    )
    LOG_FILE_LEVEL: str = Field(
        None,
        description="Уровень логирования для файла (если не указан, используется LOG_LEVEL)."
    )
    LOG_MAX_BYTES: int = Field(
        5242880,
        description="Макс. размер файла логов (в байтах), по умолчанию 5 MB (5242880)."
    )
    LOG_BACKUP_COUNT: int = Field(
        3,
        description="Число бэкапов при ротации логов."
    )
    DISABLE_EXISTING_LOGGERS: bool = Field(
        False,
        description="Отключать ли существующие логгеры при dictConfig? (по умолчанию False)."
    )

    # =====================
    # Пример дополнительных настроек
    # =====================
    DATABASE_URL: Optional[str] = Field(
        None,
        description="URL для подключения к базе данных (например, postgresql://user:pass@host:port/dbname)"
    )

    MAIN_INTERVAL: int = Field(
        30,
        description="Пример: интервал (в секундах) для фоновых задач, опросов и т.п."
    )

    # =====================
    # Свойство для разбивки QA_SERVICE_BAD_WORDS
    # =====================
    @property
    def bad_words_list(self) -> List[str]:
        """
        Удобное свойство, возвращающее список "запрещённых слов",
        разбитый по ';' и «очищенный» от пустых значений.
        """
        raw = self.QA_SERVICE_BAD_WORDS.strip()
        if not raw:
            return []
        return [w.strip() for w in raw.split(";") if w.strip()]

    class Config:
        # Pydantic будет автоматически подхватывать переменные окружения,
        # соответствующие именам полей (QA_SERVICE_PORT, QA_SERVICE_DEBUG и т.д.).
        env_file_encoding = "utf-8"
        case_sensitive = True
        # Если хотите использовать .env по умолчанию (без явного load_dotenv),
        # раскомментируйте строку ниже (и убедитесь, что .env лежит рядом):
        # env_file = ".env"


# ------------------------------------------------------------------------------
# Синглтон-функция, чтобы не создавать Settings() многократно
# ------------------------------------------------------------------------------
_settings_instance: Optional[Settings] = None


def get_settings() -> Settings:
    """
    Возвращает глобальный объект настроек (синглтон), чтобы
    не создавать объект Settings при каждом обращении.
    """
    global _settings_instance
    if _settings_instance is None:
        _settings_instance = Settings()
    return _settings_instance


# ------------------------------------------------------------------------------
# Пример использования (локальный тест)
# ------------------------------------------------------------------------------
if __name__ == "__main__":
    settings = get_settings()
    print("PORT:", settings.QA_SERVICE_PORT)
    print("DEBUG:", settings.QA_SERVICE_DEBUG)
    print("LANGUAGE:", settings.QA_SERVICE_LANG)
    print("BAD_WORDS:", settings.bad_words_list)
    print("AUTO_CORRECT:", settings.QA_SERVICE_AUTO_CORRECT)
    print("LOG_LEVEL:", settings.LOG_LEVEL)
    print("ENABLE_JSON_LOGS:", settings.ENABLE_JSON_LOGS)
    print("LOG_FILE:", settings.LOG_FILE)
    print("LOG_CONSOLE_LEVEL:", settings.LOG_CONSOLE_LEVEL)
    print("LOG_FILE_LEVEL:", settings.LOG_FILE_LEVEL)
    print("LOG_MAX_BYTES:", settings.LOG_MAX_BYTES)
    print("LOG_BACKUP_COUNT:", settings.LOG_BACKUP_COUNT)
    print("DISABLE_EXISTING_LOGGERS:", settings.DISABLE_EXISTING_LOGGERS)
    print("DATABASE_URL:", settings.DATABASE_URL)
    print("MAIN_INTERVAL:", settings.MAIN_INTERVAL)
    print("All settings:", settings.dict())
