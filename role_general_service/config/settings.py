from pydantic import AnyHttpUrl, field_validator
from pydantic_settings import BaseSettings
from functools import lru_cache
import os


class Settings(BaseSettings):
    """
    Класс конфигурации приложения.
    Содержит переменные окружения (ENV) для OpenAI,
    а также любые другие настройки микросервиса.
    """

    # --- GPT Настройки ---
    OPENAI_API_KEY: str
    OPENAI_MODEL: str = "gpt-3.5-turbo"

    # --- Общие настройки приложения ---
    ENV_STATE: str = "dev"       # dev, test, prod
    # True/False — режим отладки (логирование, autoreload и т.д.)
    DEBUG: bool = False
    PORT: int = 5001            # На каком порту запускать сервис

    # --- Пример настроек БД (если нужно) ---
    DB_HOST: str = "localhost"
    DB_PORT: int = 5432
    DB_NAME: str = "innvision_db"
    DB_USER: str = "postgres"
    DB_PASSWORD: str = ""

    # --- Пример настройки внешних сервисов (если есть) ---
    EXTERNAL_API_URL: AnyHttpUrl = "https://example.com/api"

    # --- Дополнительные параметры ---
    MAIN_INTERVAL: int = 60  # Период в секундах для фоновой проверки новых заказов

    class Config:
        """
        Опции конфигурации Pydantic:
        - env_file: указывает, откуда загружать переменные окружения
        - env_file_encoding: кодировка файла
        """
        env_file = ".env"
        env_file_encoding = "utf-8"

    @field_validator("ENV_STATE")
    def validate_env_state(cls, v):
        """
        Дополнительная валидация поля ENV_STATE (должно быть одно из: dev, test, prod).
        """
        allowed = {"dev", "test", "prod"}
        if v not in allowed:
            raise ValueError(
                f"ENV_STATE должно быть одним из {allowed}, а получено: {v}")
        return v


@lru_cache
def get_settings() -> Settings:
    """
    Используем lru_cache, чтобы настройки были синглтоном в рамках приложения.
    """
    return Settings()
