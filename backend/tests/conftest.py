import socket

import pytest


@pytest.fixture(autouse=True)
def forbid_live_network(monkeypatch):
    original_connect = socket.socket.connect
    original_connect_ex = socket.socket.connect_ex
    def local_only(sock, address):
        # Windows asyncio creates a loopback socket pair for its own event loop.
        if isinstance(address, tuple) and address[0] in ('127.0.0.1', '::1'):
            return original_connect(sock, address)
        raise AssertionError('Default tests must not connect to live services')
    def local_only_ex(sock, address):
        if isinstance(address, tuple) and address[0] in ('127.0.0.1', '::1'):
            return original_connect_ex(sock, address)
        raise AssertionError('Default tests must not connect to live services')
    monkeypatch.setattr(socket.socket, 'connect', local_only)
    monkeypatch.setattr(socket.socket, 'connect_ex', local_only_ex)
    for name in ('AUSPOST_API_KEY', 'AUSPOST_API_SECRET', 'AUSPOST_ACCOUNT_NUMBER'):
        monkeypatch.delenv(name, raising=False)
