"""The network guard: no internet socket opens, no host name is looked up, and the suffix list
comes with the program.

tests/conftest.py installs the guard before the first test, so the whole suite runs guarded. These
tests check what the guard blocks and what it leaves alone (Unix-domain sockets, which Qt and the
operating system use to talk to other processes on this computer), that installing it again changes
nothing, and that tldextract reads the public-suffix list it ships with instead of fetching one.
Apart from the brief's test_guard_blocks_connect, the tests send to and look up only what is on
this computer (127.0.0.1, ::1, localhost), so that a guard that failed would still put nothing
onto a network.
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
SOCKET_METHODS = ("connect", "connect_ex", "sendto", "sendmsg", "bind", "listen")
SOCKET_FUNCTIONS = (
    "create_connection",
    "create_server",
    "getaddrinfo",
    "gethostbyname",
    "gethostbyname_ex",
    "gethostbyaddr",
    "getnameinfo",
)


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
        socket.getaddrinfo("localhost", 443)
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
        "sendmsg": lambda sock: sock.sendmsg([b"ping"], [], 0, (host, 9)),
        "bind": lambda sock: sock.bind((host, 0)),
        "listen": lambda sock: sock.listen(1),
    }
    datagrams = method in {"sendto", "sendmsg"}
    try:
        sock = socket.socket(family, socket.SOCK_DGRAM if datagrams else socket.SOCK_STREAM)
    except OSError:
        pytest.skip("This computer has no sockets of that family.")
    with sock, pytest.raises(NetworkBlockedError, match=re.escape(MESSAGE)):
        calls[method](sock)


@pytest.mark.parametrize(
    "call",
    [
        pytest.param(lambda: socket.create_server(("127.0.0.1", 0)), id="create_server-IPv4"),
        pytest.param(
            lambda: socket.create_server(("::1", 0), family=socket.AF_INET6),
            id="create_server-IPv6",
        ),
        pytest.param(lambda: socket.gethostbyname("localhost"), id="gethostbyname"),
        pytest.param(lambda: socket.gethostbyname_ex("localhost"), id="gethostbyname_ex"),
        pytest.param(lambda: socket.gethostbyaddr("127.0.0.1"), id="gethostbyaddr"),
        pytest.param(lambda: socket.getnameinfo(("127.0.0.1", 80), 0), id="getnameinfo"),
    ],
)
def test_servers_and_name_lookups_raise_the_guards_own_error(call):
    # create_server would otherwise fail inside bind() with a bare OSError that says "None": the
    # standard library re-raises bind's error without its type or message.
    with pytest.raises(NetworkBlockedError, match=re.escape(MESSAGE)):
        call()


def test_getfqdn_makes_no_lookup():
    install_network_guard()
    # getfqdn asks gethostbyaddr, which is blocked, and keeps the error to itself: the name it was
    # given comes back. Without the guard a Mac answers "1.0.0.127.in-addr.arpa".
    assert socket.getfqdn("127.0.0.1") == "127.0.0.1"


def test_local_sockets_still_work(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    install_network_guard()
    # The socket's name is relative to the folder: a Unix socket's full path is limited to about a
    # hundred characters, which a test folder on a Mac easily exceeds.
    monkeypatch.chdir(tmp_path)

    left, right = socket.socketpair()
    with left, right:
        left.sendall(b"ping")
        assert right.recv(4) == b"ping"
        left.sendmsg([b"pong"])
        assert right.recv(4) == b"pong"

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
        sender.sendmsg([b"pong"], [], 0, "datagram.sock")
        assert receiver.recv(4) == b"pong"


def test_installing_twice_changes_nothing():
    install_network_guard()
    methods = {name: getattr(socket.socket, name) for name in SOCKET_METHODS}
    functions = {name: getattr(socket, name) for name in SOCKET_FUNCTIONS}
    extractor = tldextract.extract
    modules_extractor = tldextract.tldextract.TLD_EXTRACTOR

    install_network_guard()

    for name, method in methods.items():
        assert getattr(socket.socket, name) is method, name  # not wrapped a second time
    for name, function in functions.items():
        assert getattr(socket, name) is function, name
    assert tldextract.extract is extractor
    assert tldextract.tldextract.TLD_EXTRACTOR is modules_extractor


def test_tldextract_reads_the_list_it_ships_with(caplog: pytest.LogCaptureFixture):
    install_network_guard()
    extractor = tldextract.extract
    assert isinstance(extractor, tldextract.TLDExtract)
    assert extractor.suffix_list_urls == ()  # no address to fetch a list from
    assert extractor.fallback_to_snapshot  # so the bundled snapshot is the list

    parts = tldextract.extract("https://forums.bbc.co.uk/news")

    assert (parts.subdomain, parts.domain, parts.suffix) == ("forums", "bbc", "co.uk")
    assert "Public Suffix List" not in caplog.text


def test_the_functions_a_program_took_earlier_use_the_same_extractor():
    install_network_guard()
    # "from tldextract import extract" before the guard went on holds the submodule's function,
    # which reads this global each time it is called.
    assert tldextract.tldextract.TLD_EXTRACTOR is tldextract.extract
    assert tldextract.tldextract.extract is not tldextract.extract

    assert tldextract.tldextract.extract("https://forums.bbc.co.uk/news").suffix == "co.uk"


def test_tldextract_leaves_no_cache_behind(tmp_path: Path):
    """tldextract's own cache would write a file under ~/.cache; the app keeps its files in its
    data folder only, and a cache that cannot be written makes tldextract warn about the list.
    The function a program took before the guard went on must be as quiet as the new one.
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
        "from tldextract import extract as taken_before\n"
        "from themask.netguard import install_network_guard\n"
        "install_network_guard()\n"
        "import tldextract\n"
        "for extract in (tldextract.extract, taken_before):\n"
        "    print(extract('https://forums.bbc.co.uk/news').suffix)\n"
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
    assert result.stdout.split() == ["co.uk", "co.uk"]
    assert result.stderr == ""
    assert list(home.rglob("*")) == []
