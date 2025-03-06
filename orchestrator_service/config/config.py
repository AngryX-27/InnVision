# config.py

import os
from typing import Optional, List

# Вместо validator, root_validator:
# - field_validator для отдельных полей,
# - model_validator для общей валидации модели.
from pydantic_settings import BaseSettings
from pydantic import (
    Field, AnyUrl,
    field_validator, model_validator,
    ValidationError
)

########################################################################
# 0. Дополнительные валидаторы (кастомные), если нужно
########################################################################


def validate_url_maybe_none(v: Optional[str]) -> Optional[str]:
    """
    Пример: проверяем, что URL корректна, если не None.
    Если нужно более строгая проверка — используйте pydantic.AnyUrl.
    """
    if v is not None and not v.startswith("http"):
        raise ValueError(f"Invalid URL: {v}")
    return v


########################################################################
# 1. Базовая модель (Settings)
#    Содержит большинство полей с описанием.
########################################################################

class Settings(BaseSettings):
    """
    Общие настройки приложения. Pydantic автоматически читает переменные окружения 
    (или .env) + выполняет валидацию.

    При необходимости можно подключить YAML/JSON:
      - см. model_validator (mode="before"), открывать config.yaml, парсить, мёржить с env.
    """

    # Пример: env_prefix = "INNVISION_"
    # Если хотите, чтобы все переменные имели префикс "INNVISION_"

    ############### Основные параметры Flask / Orchestrator ###############
    ORCHESTRATOR_HOST: str = Field(
        "0.0.0.0", description="Хост для запуска Flask-сервера")
    ORCHESTRATOR_PORT: int = Field(
        5000, description="Порт для запуска Flask-сервера")
    ORCHESTRATOR_DEBUG: bool = Field(
        True, description="Включить Debug-режим Flask (False в продакшене)")

    ############### Логирование ###############
    LOG_LEVEL: str = Field(
        "INFO", description="Уровень логирования (DEBUG, INFO, WARNING, ERROR, CRITICAL)")
    LOG_FILE: Optional[str] = Field(
        None, description="Путь к файлу логов (если не None, будем писать в файл)")
    LOG_ROTATION_MAXBYTES: int = Field(
        1_000_000, description="Максимальный размер файла логов (байты)")
    LOG_ROTATION_BACKUPCOUNT: int = Field(
        5, description="Число бэкапов для ротации логов")

    ############### База данных (если нужно) ###############
    DATABASE_URL: Optional[AnyUrl] = Field(
        None, description="URL подключения к базе (Postgres, SQLite и т. д.)")

    ############### Секреты ###############
    SECRET_KEY: Optional[str] = Field(
        None,
        description="Секретный ключ Flask (JWT, cookies). Обязательно при продакшене."
    )

    ############### Внешние сервисы ###############
    ROLE_SERVICE_URL: Optional[str] = Field(
        None, description="URL сервиса Role General"
    )
    QA_SERVICE_URL: Optional[str] = Field(
        None, description="URL сервиса QA"
    )
    TRANSLATION_SERVICE_URL: Optional[str] = Field(
        None, description="URL сервиса Translation"
    )

    # Возможно, список fallback-сервисов
    FALLBACK_URLS: Optional[List[str]] = Field(
        None, description="Список резервных сервисов")

    ############### Другие параметры ###############
    OPENAI_API_KEY: Optional[str] = Field(
        None, description="Токен OpenAI (если нужно)")
    REQUEST_TIMEOUT: int = Field(
        5, description="Таймаут при обращении к внешним сервисам (сек).")
    REQUEST_RETRIES: int = Field(
        3, description="Число повторных запросов при сетевых ошибках.")

    ############### Pydantic config ###############
    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        # env_prefix = "INNVISION_"  # Раскомментируйте, если нужно префикс
        # Можно и strict: case_sensitive = True

    ############### Валидаторы (Pydantic 2) ###############
    @field_validator("LOG_LEVEL")
    def validate_log_level(cls, v):
        allowed = ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]
        if v.upper() not in allowed:
            raise ValueError(f"LOG_LEVEL must be one of {allowed}")
        return v.upper()

    @field_validator("ROLE_SERVICE_URL", "QA_SERVICE_URL", "TRANSLATION_SERVICE_URL", pre=True)
    def validate_service_urls(cls, v):
        """
        Простой check: если не None, должно начинаться с http.
        При желании можно использовать AnyUrl.
        """
        if v is None:
            return v
        if not v.startswith("http"):
            raise ValueError(f"Invalid service URL: {v}")
        return v

    @model_validator(mode="after")
    def secret_key_required_in_prod(cls, values):
        """
        Если ORCHESTRATOR_DEBUG=False, желательно иметь SECRET_KEY.
        """
        debug_mode = values.get("ORCHESTRATOR_DEBUG", True)
        secret_key = values.get("SECRET_KEY")
        if not debug_mode and not secret_key:
            raise ValueError(
                "SECRET_KEY is required in production environment!")
        return values

    # Пример model_validator — если нужно объединять YAML/JSON
    # @model_validator(mode="before")
    # def load_yaml_config(cls, values):
    #     # Если хотим дополнительно загрузить config.yaml
    #     # и мёржить в values.
    #     # (Псевдокод)
    #     # import yaml
    #     # with open("config.yaml", "r") as f:
    #     #     data = yaml.safe_load(f)
    #     # for key, val in data.items():
    #     #     if key not in values or values[key] is None:
    #     #         values[key] = val
    #     return values


########################################################################
# 2. Специальные классы для окружений
########################################################################

class DevSettings(Settings):
    """
    Настройки для разработки (dev).
    """
    ORCHESTRATOR_DEBUG: bool = True
    LOG_LEVEL: str = "DEBUG"

    class Config:
        env_file = ".env.dev"
        env_file_encoding = "utf-8"


class ProdSettings(Settings):
    """
    Настройки для продакшена:
      - Debug = False
      - SECRET_KEY обязателен
      - LOG_LEVEL = INFO
    """
    ORCHESTRATOR_DEBUG: bool = False
    LOG_LEVEL: str = "INFO"

    class Config:
        env_file = ".env.prod"
        env_file_encoding = "utf-8"


class TestSettings(Settings):
    """
    Настройки для тестов / CI.
    Например, в памяти база (sqlite:///:memory:).
    """
    ORCHESTRATOR_DEBUG: bool = False
    LOG_LEVEL: str = "ERROR"
    DATABASE_URL: Optional[AnyUrl] = "sqlite:///:memory:"  # тестовая in-memory

    class Config:
        env_file = ".env.test"
        env_file_encoding = "utf-8"


########################################################################
# 3. Функция, которая определяет окружение (DEV, PROD, TEST)
########################################################################

def load_config() -> Settings:
    """
    Читает переменную APP_ENV, возвращает соответствующий объект настроек:
      - 'prod' => ProdSettings
      - 'test' => TestSettings
      - иначе => DevSettings
    """
    app_env = os.getenv("APP_ENV", "dev").lower()

    if app_env == "prod":
        return ProdSettings()
    elif app_env == "test":
        return TestSettings()
    else:
        # По умолчанию dev
        return DevSettings()


########################################################################
# Пример использования:
########################################################################

# settings = load_config()
# print(settings.dict())
# print(settings.LOG_LEVEL, settings.ORCHESTRATOR_DEBUG, settings.DATABASE_URL)
