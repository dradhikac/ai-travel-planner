"""Tests verifying the network socket guard fixture."""

import socket

import pytest


def test_unit_test_network_socket_is_prohibited() -> None:
    """Standard unit tests must fail loudly if they attempt a network connection."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    with pytest.raises(
        RuntimeError, match="Network socket connection prohibited in unit tests"
    ):
        sock.connect(("127.0.0.1", 80))


def test_unit_test_connect_ex_is_prohibited() -> None:
    """Standard unit tests must fail loudly if they attempt connect_ex."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    with pytest.raises(
        RuntimeError, match="Network socket connection prohibited in unit tests"
    ):
        sock.connect_ex(("127.0.0.1", 80))


@pytest.mark.integration
def test_integration_marked_test_bypasses_socket_guard() -> None:
    """Integration-marked tests are permitted to initiate network sockets."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    # The guard is bypassed for @pytest.mark.integration.
    # connect_ex returns an errno code rather than raising the guard RuntimeError.
    res = sock.connect_ex(("127.0.0.1", 1))
    assert isinstance(res, int)
    sock.close()
