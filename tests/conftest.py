"""Keep the public regression suite offline; fixtures use temporary storage."""
import socket

import pytest


@pytest.fixture(autouse=True)
def no_external_connections(monkeypatch):
    def blocked(*args, **kwargs):
        raise AssertionError('Tests must mock network calls; external connections are disabled')
    monkeypatch.setattr(socket.socket, 'connect', blocked)
    monkeypatch.setattr(socket.socket, 'connect_ex', blocked)
    monkeypatch.setattr(socket, 'create_connection', blocked)
