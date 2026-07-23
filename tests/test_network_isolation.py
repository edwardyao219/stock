from __future__ import annotations

import socket

import pytest


def test_external_network_connections_are_blocked() -> None:
    with pytest.raises(AssertionError, match="external network access"):
        socket.getaddrinfo("example.com", 443)

    with socket.socket() as client:
        with pytest.raises(AssertionError, match="external network access"):
            client.connect(("203.0.113.1", 443))
        with pytest.raises(AssertionError, match="external network access"):
            client.connect_ex(("203.0.113.1", 443))


def test_local_unix_socket_paths_remain_available() -> None:
    with socket.socket(socket.AF_UNIX) as client:
        with pytest.raises(FileNotFoundError):
            client.connect(b"/tmp/stock-test-network-isolation.sock")
