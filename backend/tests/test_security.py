import pytest

from app.security import decrypt_secret, encrypt_secret, hash_password, verify_password


def test_password_roundtrip():
    hashed = hash_password("correct horse battery")
    assert hashed != "correct horse battery"
    assert verify_password(hashed, "correct horse battery")
    assert not verify_password(hashed, "wrong password")


def test_short_password_rejected():
    with pytest.raises(ValueError):
        hash_password("short")


def test_secret_encryption_roundtrip():
    token = encrypt_secret({"api_key": "abc"})
    assert "abc" not in token
    assert decrypt_secret(token) == {"api_key": "abc"}
