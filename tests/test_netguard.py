"""The network guard: no internet socket opens, and the suffix list comes with the program.

tests/conftest.py installs the guard before the first test, so the whole suite runs guarded. These
tests check what the guard blocks and what it leaves alone (Unix-domain sockets, which Qt and the
operating system use to talk to other processes on this computer), that installing it again changes
nothing, and that tldextract reads the public-suffix list it ships with instead of fetching one.
"""

from __future__ import annotations

import os
import re
import socket
import subprocess
import sys
from typing import TYPE_CHECKING

import pytest
import tldextract

from themask.model import PlaceholderType
from themask.netguard import NetworkBlockedError, install_network_guard

if TYPE_CHECKING:
    from pathlib import Path

    from themask.detect.engine import Engine

MESSAGE = "The MASK never uses the network."
SOCKET_METHODS = ("connect", "connect_ex", "sendto", "bind", "listen")


def test_guard_blocks_connect():
    install_network_guard()
    with pytest.raises(NetworkBlockedError):
        socket.create_connection(("127.0.0.1", 9))
    with pytest.raises(NetworkBlockedError):
        socket.getaddrinfo("example.com", 443)


def test_url_recognizer_works_offline(engine: Engine, caplog: pytest.LogCaptureFixture):
    install_network_guard()
    findings = engine.analyze("see https://www.northwind.example/terms")
    assert any(f.type == PlaceholderType.URL for f in findings)
    assert "Public Suffix List" not in caplog.text


def test_the_error_is_an_os_error_with_a_plain_message():
    assert issubclass(NetworkBlockedError, OSError)
    with pytest.raises(OSError) as raised:
        socket.getaddrinfo("example.com", 443)
    assert type(raised.value) is NetworkBlockedError
    assert str(raised.value) == MESSAGE


@pytest.mark.parametrize("method", SOCKET_METHODS)
@pytest.mark.parametrize("family", [socket.AF_INET, socket.AF_INET6], ids=["IPv4", "IPv6"])
def test_internet_sockets_cannot_connect_send_bind_or_listen(family, method):
    host = "127.0.0.1" if family == socket.AF_INET else "::1"
    calls = {
        "connect": lambda sock: sock.connect((host, 9)),
        "connect_ex": lambda sock: sock.connect_ex((host, 9)),
        "sendto": lambda sock: sock.sendto(b"ping", (host, 9)),
        "bind": lambda sock: sock.bind((host, 0)),
        "listen": lambda sock: sock.listen(1),
    }
    try:
        sock = socket.socket(
            family, socket.SOCK_DGRAM if method == "sendto" else socket.SOCK_STREAM
        )
    except OSError:
        pytest.skip("This computer has no sockets of that family.")
    with sock, pytest.raises(NetworkBlockedError, match=re.escape(MESSAGE)):
        calls[method](sock)


def test_local_sockets_still_work(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    install_network_guard()
    # The socket's name is relative to the folder: a Unix socket's full path is limited to about a
    # hundred characters, which a test folder on a Mac easily exceeds.
    monkeypatch.chdir(tmp_path)

    left, right = socket.socketpair()
    with left, right:
        left.sendall(b"ping")
        assert right.recv(4) == b"ping"

    with (
        socket.socket(socket.AF_UNIX) as server,
        socket.socket(socket.AF_UNIX) as client,
        socket.socket(socket.AF_UNIX) as second_client,
    ):
        server.bind("stream.sock")
        server.listen(2)
        client.connect("stream.sock")
        assert second_client.connect_ex("stream.sock") == 0
        connection, _ = server.accept()
        with connection:
            client.sendall(b"ping")
            assert connection.recv(4) == b"ping"

    with (
        socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM) as receiver,
        socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM) as sender,
    ):
        receiver.bind("datagram.sock")
        sender.sendto(b"ping", "datagram.sock")
        assert receiver.recv(4) == b"ping"


def test_installing_twice_changes_nothing():
    install_network_guard()
    methods = {name: getattr(socket.socket, name) for name in SOCKET_METHODS}
    functions = {name: getattr(socket, name) for name in ("create_connection", "getaddrinfo")}
    extractor = tldextract.extract

    install_network_guard()

    for name, method in methods.items():
        assert getattr(socket.socket, name) is method, name  # not wrapped a second time
    for name, function in functions.items():
        assert getattr(socket, name) is function, name
    assert tldextract.extract is extractor


def test_tldextract_reads_the_list_it_ships_with(caplog: pytest.LogCaptureFixture):
    install_network_guard()
    extractor = tldextract.extract
    assert isinstance(extractor, tldextract.TLDExtract)
    assert extractor.suffix_list_urls == ()  # no address to fetch a list from
    assert extractor.fallback_to_snapshot  # so the bundled snapshot is the list

    parts = tldextract.extract("https://forums.bbc.co.uk/news")

    assert (parts.subdomain, parts.domain, parts.suffix) == ("forums", "bbc", "co.uk")
    assert "Public Suffix List" not in caplog.text


def test_tldextract_leaves_no_cache_behind(tmp_path: Path):
    """tldextract's own cache would write a file under ~/.cache; the app keeps its files in its
    data folder only, and a cache that cannot be written makes tldextract warn about the list.
    """
    home = tmp_path / "home"
    home.mkdir()
    environment = {
        key: value
        for key, value in os.environ.items()
        if key not in {"XDG_CACHE_HOME", "TLDEXTRACT_CACHE"}
    }
    environment["HOME"] = str(home)  # where tldextract looks for its cache folder
    program = (
        "from themask.netguard import install_network_guard\n"
        "install_network_guard()\n"
        "import tldextract\n"
        "print(tldextract.extract('https://forums.bbc.co.uk/news').suffix)\n"
    )

    result = subprocess.run(
        [sys.executable, "-c", program],
        env=environment,
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "co.uk"
    assert result.stderr == ""
    assert list(home.rglob("*")) == []
