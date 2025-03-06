"""
config.py — Расширенная конфигурация для Translation Service,
с учётом:
(2) Доп. проверка корректности DB_URL (через urllib.parse).
(4) Логика подстановки значений при ENV=production (DEBUG=False, LOG_LEVEL=WARNING, ...).
"""

import os
import logging
import urllib.parse
from typing import Optional

from pydantic_settings import BaseSettings
from pydantic import Field, model_validator, field_validator

from urllib.parse import ParseResult


def select_env_file(env_value: str) -> str:
    """
    Для упрощения:
      - production -> ".env.production"
      - иначе -> ".env.development"
    (Можно расширять, если есть staging, testing и т. д.)
    """
    if env_value == "production":
        return ".env.production"
    else:
        return ".env.development"


class Settings(BaseSettings):
    """
    Основные настройки приложения. Читаются из:
      1) переменных окружения
      2) файла .env (определяется select_env_file(os.getenv("ENV", "development")))
    """

    ##########################
    # Среда (development / production / ...)
    ##########################
    ENV: str = Field("development", env="ENV")

    ##########################
    # Порт приложения
    ##########################
    PORT: int = Field(5005, env="PORT")

    ##########################
    # Строка подключения к PostgreSQL
    ##########################
    DB_URL: str = Field(
        "postgresql://user:pass@localhost:5432/db_name",
        env="DB_URL",
        description="Строка подключения к БД (PostgreSQL)."
    )

    # Ключи API (GPT, DeepL)
    OPENAI_API_KEY: Optional[str] = Field(None, env="OPENAI_API_KEY")
    DEEPL_API_KEY: Optional[str] = Field(None, env="DEEPL_API_KEY")

    # Вместо GOOGLE_API_KEY теперь используем JSON сервисного аккаунта
    GOOGLE_SERVICE_ACCOUNT_JSON: Optional[str] = Field(
        None, env="GOOGLE_SERVICE_ACCOUNT_JSON",
        description="Путь к JSON-файлу сервисного аккаунта Google."
    )

    # Доп. настройки
    LOG_LEVEL: str = Field("INFO", env="LOG_LEVEL")
    DEBUG: bool = Field(False, env="DEBUG")
    ALLOW_CHUNKING: bool = Field(False, env="ALLOW_CHUNKING")

    ##########################
    # 2) Доп. проверка DB_URL
    ##########################
    @field_validator("DB_URL")
    @classmethod
    def validate_db_url(cls, v: str) -> str:
        """
        Убедимся, что строка начинается с postgresql:// и 
        что при парсинге у нас есть host и база в пути.
        """
        if not v.startswith("postgresql://"):
            raise ValueError(
                f"DB_URL must start with 'postgresql://', got '{v}' instead."
            )
        parsed: ParseResult = urllib.parse.urlparse(v)
        # scheme='postgresql', netloc='user:pass@localhost:5432', path='/db_name'
        if parsed.scheme != "postgresql":
            raise ValueError(
                f"DB_URL scheme must be 'postgresql', got '{parsed.scheme}'."
            )
        if not parsed.netloc or not parsed.path:
            raise ValueError(
                f"DB_URL is missing host or database path. netloc='{parsed.netloc}', path='{parsed.path}'."
            )
        return v

    ##########################
    # Валидатор ENV
    ##########################
    @field_validator("ENV")
    @classmethod
    def validate_env(cls, v):
        allowed_envs = ("development", "staging", "production")
        if v not in allowed_envs:
            raise ValueError(
                f"ENV must be one of {allowed_envs}, got '{v}' instead."
            )
        return v

    ##########################
    # Валидатор LOG_LEVEL
    ##########################
    @field_validator("LOG_LEVEL")
    @classmethod
    def validate_log_level(cls, v: str) -> str:
        valid_levels = ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]
        if v.upper() not in valid_levels:
            raise ValueError(
                f"LOG_LEVEL must be one of {valid_levels}, got '{v}' instead."
            )
        return v.upper()

    ##########################
    # Проверка GOOGLE_SERVICE_ACCOUNT_JSON
    ##########################

    @field_validator("GOOGLE_SERVICE_ACCOUNT_JSON")
    @classmethod
    def validate_google_service_account_json(cls, v):
        """
        Если указан путь к JSON сервисного аккаунта, проверяем, что файл реально существует.
        """
        if v:
            if not os.path.isfile(v):
                raise ValueError(
                    f"Google service account JSON file not found: '{v}'"
                )
        return v

    ##########################
    # 4) Логика подстановки значений при ENV=production
    ##########################
    @model_validator(mode="after")
    def apply_production_overrides(cls, self: "Settings") -> "Settings":
        """
        Если ENV=production, принудительно устанавливаем DEBUG=False,
        LOG_LEVEL="WARNING" (или что вам нужно).
        (Переписано под Pydantic 2.x: получаем self, а не dict.)
        """
        env = self.ENV or "development"
        if env == "production":
            self.DEBUG = False
            all_levels = ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]
            current_level = self.LOG_LEVEL
            if all_levels.index(current_level) < all_levels.index("WARNING"):
                self.LOG_LEVEL = "WARNING"
        return self

    class Config:
        # Выбираем .env-файл на основе ENV
        env_file = select_env_file(os.getenv("ENV", "development"))
        env_file_encoding = "utf-8"
        case_sensitive = True


# Создаём объект настроек (singleton)
settings = Settings()

logging.debug(
    f"Loaded config from env_file='{Settings.Config.env_file}', ENV='{settings.ENV}'"
)
