"""Общие настройки тестов: безопасные значения окружения, если .env не задан."""

import os

from cryptography.fernet import Fernet

os.environ.setdefault("DATABASE_URL", "postgresql+psycopg://test:test@localhost:5432/test")
os.environ.setdefault("SECRET_KEY", "test-secret")
os.environ.setdefault("ENCRYPTION_KEY", Fernet.generate_key().decode())
os.environ.setdefault("SCHEDULER_ENABLED", "false")
