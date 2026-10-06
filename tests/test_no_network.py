"""The conftest guards hold: a test that tried a live host or started a process would fail, not spend the poller's budget.

One test per guard. The subprocess tests start only `python -c pass`, and the curl_cffi tests aim at
the loopback address 127.0.0.1, so a missing guard fails a test without touching any real host.
"""
import socket
import subprocess
import sys

import pytest

from tests.conftest import NetworkBlocked

HARMLESS_COMMAND = [sys.executable, "-c", "pass"]


def test_a_socket_connect_in_a_test_is_refused():
    s = socket.socket()
    try:
        with pytest.raises(NetworkBlocked):
            s.connect(("127.0.0.1", 9))
    finally:
        s.close()


def test_create_connection_in_a_test_is_refused():
    with pytest.raises(NetworkBlocked):
        socket.create_connection(("example.com", 443), timeout=1)


@pytest.mark.parametrize(
    "start_process",
    [subprocess.run, subprocess.call, subprocess.check_call, subprocess.check_output, subprocess.Popen],
    ids=["run", "call", "check_call", "check_output", "Popen"],
)
def test_starting_a_process_in_a_test_is_refused(start_process):
    with pytest.raises(NetworkBlocked):
        start_process(HARMLESS_COMMAND)


def test_a_curl_cffi_session_request_in_a_test_is_refused():
    cffi_requests = pytest.importorskip("curl_cffi.requests", reason="curl_cffi is not installed on this machine")
    with cffi_requests.Session() as session:
        with pytest.raises(NetworkBlocked):
            session.get("http://127.0.0.1:9/")


@pytest.mark.parametrize(
    "verb, args",
    [("get", ("http://127.0.0.1:9/",)), ("post", ("http://127.0.0.1:9/",)), ("request", ("GET", "http://127.0.0.1:9/"))],
)
def test_a_curl_cffi_module_level_call_in_a_test_is_refused(verb, args):
    cffi_requests = pytest.importorskip("curl_cffi.requests", reason="curl_cffi is not installed on this machine")

    with pytest.raises(NetworkBlocked):
        getattr(cffi_requests, verb)(*args)
