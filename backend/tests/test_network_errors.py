"""Сетевые сбои коннекторов превращаются в понятные ошибки."""

import httpx
import pytest

from app.connectors.base import ConnectorError, NetworkError
from app.connectors.bing import BingConnector


def failing(exc_cls, text):
    def handler(request):
        raise exc_cls(text, request=request)
    return httpx.MockTransport(handler)


def test_dns_failure_is_readable_connector_error():
    transport = failing(httpx.ConnectError, "[Errno 11002] getaddrinfo failed")
    connector = BingConnector({"api_key": "k"}, transport=transport)
    with pytest.raises(NetworkError, match="адрес не найден") as info:
        connector.check_access()
    assert isinstance(info.value, ConnectorError)
    assert "ssl.bing.com" in str(info.value)


def test_timeout_is_readable():
    connector = BingConnector({"api_key": "k"}, transport=failing(httpx.ReadTimeout, "timed out"))
    with pytest.raises(NetworkError, match="не ответил вовремя"):
        connector.check_access()
