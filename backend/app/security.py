"""Хэширование паролей и шифрование секретов.

* Пароли учётных записей хранятся только в виде хэша Argon2id.
* Refresh-токены и API-ключи систем шифруются Fernet (AES-128-CBC + HMAC-SHA256).
  Ключ шифрования берётся из переменной окружения ``ENCRYPTION_KEY`` и никогда
  не попадает в БД или репозиторий.
"""

from __future__ import annotations

import json
from typing import Any

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError
from cryptography.fernet import Fernet, InvalidToken

from app.config import get_settings

_password_hasher = PasswordHasher()

#: Минимальная длина пароля учётной записи.
MIN_PASSWORD_LENGTH = 10


class SecretDecryptionError(RuntimeError):
    """Секрет не удалось расшифровать (сменился ENCRYPTION_KEY или данные повреждены)."""


def hash_password(password: str) -> str:
    """Вернуть хэш Argon2id для пароля.

    Args:
        password: Пароль в открытом виде.

    Raises:
        ValueError: Пароль короче :data:`MIN_PASSWORD_LENGTH` символов.
    """
    if len(password) < MIN_PASSWORD_LENGTH:
        raise ValueError(f"Пароль должен быть не короче {MIN_PASSWORD_LENGTH} символов")
    return _password_hasher.hash(password)


def verify_password(password_hash: str, password: str) -> bool:
    """Проверить пароль по хэшу. Никогда не выбрасывает исключений проверки."""
    try:
        return _password_hasher.verify(password_hash, password)
    except (VerificationError, InvalidHashError):
        return False


def _fernet() -> Fernet:
    return Fernet(get_settings().encryption_key.encode())


def encrypt_secret(data: dict[str, Any]) -> str:
    """Зашифровать словарь секретов (токены, ключи) для хранения в БД."""
    return _fernet().encrypt(json.dumps(data).encode()).decode()


def decrypt_secret(token: str) -> dict[str, Any]:
    """Расшифровать секреты, сохранённые :func:`encrypt_secret`.

    Raises:
        SecretDecryptionError: Токен не расшифровывается текущим ключом.
    """
    try:
        return json.loads(_fernet().decrypt(token.encode()))
    except InvalidToken as exc:
        raise SecretDecryptionError("Не удалось расшифровать секрет") from exc


def generate_encryption_key() -> str:
    """Сгенерировать новый ключ для ``ENCRYPTION_KEY``."""
    return Fernet.generate_key().decode()
