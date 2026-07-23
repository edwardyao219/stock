from __future__ import annotations

import socket
from collections.abc import Generator

import pytest

_LOCAL_HOSTS = {"127.0.0.1", "::1", "localhost"}


@pytest.fixture(autouse=True)
def block_external_network(monkeypatch: pytest.MonkeyPatch) -> Generator[None, None, None]:
    original_getaddrinfo = socket.getaddrinfo
    original_connect = socket.socket.connect
    original_connect_ex = socket.socket.connect_ex

    def guarded_getaddrinfo(host: object, *args: object, **kwargs: object) -> object:
        if host is None or str(host).lower() in _LOCAL_HOSTS:
            return original_getaddrinfo(host, *args, **kwargs)
        raise AssertionError(f"external network access is disabled in tests: {host}")

    def guarded_connect(sock: socket.socket, address: object) -> object:
        if isinstance(address, (str, bytes)):
            return original_connect(sock, address)
        host = address[0] if isinstance(address, tuple) else None
        if host is not None and str(host).lower() in _LOCAL_HOSTS:
            return original_connect(sock, address)
        raise AssertionError(f"external network access is disabled in tests: {address}")

    def guarded_connect_ex(sock: socket.socket, address: object) -> object:
        if isinstance(address, (str, bytes)):
            return original_connect_ex(sock, address)
        host = address[0] if isinstance(address, tuple) else None
        if host is not None and str(host).lower() in _LOCAL_HOSTS:
            return original_connect_ex(sock, address)
        raise AssertionError(f"external network access is disabled in tests: {address}")

    monkeypatch.setattr(socket, "getaddrinfo", guarded_getaddrinfo)
    monkeypatch.setattr(socket.socket, "connect", guarded_connect)
    monkeypatch.setattr(socket.socket, "connect_ex", guarded_connect_ex)
    yield
