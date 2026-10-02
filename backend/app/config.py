"""Настройки приложения.

Все параметры окружения (строка подключения к БД, ключи, порт) читаются из файла
``.env`` в корне репозитория или из переменных окружения. Это позволяет переносить
приложение с localhost на сервер без изменения кода.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from zoneinfo import ZoneInfo

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

#: Корень репозитория (``<repo>/backend/app/config.py`` -> ``<repo>``).
REPO_ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    """Параметры приложения, загружаемые из окружения.

    Имена переменных окружения совпадают с именами полей в верхнем регистре,
    например ``DATABASE_URL`` или ``ENCRYPTION_KEY``.
    """

    model_config = SettingsConfigDict(
        env_file=REPO_ROOT / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # --- Инфраструктура -------------------------------------------------------
    database_url: str = Field(
        description="Строка подключения SQLAlchemy, например "
        "postgresql+psycopg://seo_dashboard:***@localhost:5432/seo_dashboard",
    )
    app_host: str = "127.0.0.1"
    app_port: int = 8000
    public_base_url: str = Field(
        default="http://localhost:8000",
        description="Внешний адрес приложения; нужен для OAuth redirect URI.",
    )

    # --- Безопасность ---------------------------------------------------------
    secret_key: str = Field(description="Ключ подписи cookie сессии (случайная строка).")
    encryption_key: str = Field(
        description="Ключ Fernet для шифрования токенов и API-ключей в БД.",
    )
    session_max_age_days: int = 14
    session_cookie_secure: bool = Field(
        default=False,
        description="Включить на сервере с HTTPS, чтобы cookie передавались только по TLS.",
    )

    # --- Сбор данных ----------------------------------------------------------
    app_timezone: str = Field(
        default="Europe/Minsk",
        description="Часовой пояс планировщика и отображения «вчера/сегодня».",
    )
    scheduler_enabled: bool = True
    daily_sync_hour: int = Field(default=4, ge=0, le=23)
    daily_sync_minute: int = Field(default=0, ge=0, le=59)
    rewrite_window_days: int = Field(
        default=5,
        description="Сколько последних дней перезабирается при каждом запуске.",
    )
    raw_retention_days: int = 90
    default_signal_threshold_pct: float = 10.0

    # --- OAuth-приложения -----------------------------------------------------
    google_client_id: str | None = None
    google_client_secret: str | None = None
    yandex_client_id: str | None = None
    yandex_client_secret: str | None = None

    # --- Фронтенд -------------------------------------------------------------
    frontend_dist: Path = REPO_ROOT / "frontend" / "dist"

    @property
    def tz(self) -> ZoneInfo:
        """Часовой пояс приложения как объект :class:`zoneinfo.ZoneInfo`."""
        return ZoneInfo(self.app_timezone)


@lru_cache
def get_settings() -> Settings:
    """Вернуть единственный экземпляр настроек (кэшируется на время жизни процесса)."""
    return Settings()  # type: ignore[call-arg]
