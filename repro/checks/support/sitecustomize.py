"""Loaded automatically in every harness subprocess (it is first on PYTHONPATH).

Agent-written code runs offline: any attempt to open a network connection raises.
"""
import socket as _socket


def _blocked(*_args, **_kwargs):
    raise OSError("network access is disabled in the reproduction harness")


_socket.socket.connect = _blocked
_socket.socket.connect_ex = _blocked
_socket.create_connection = _blocked
_socket.getaddrinfo = _blocked
