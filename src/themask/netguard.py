"""The network guard: The MASK never uses the network, and this makes sure of it.

``install_network_guard`` runs first thing at startup, and the tests' conftest runs it before the
first test, so the whole suite runs guarded and proves the app needs no network. From then on,
code in this process that tries to reach another computer gets a ``NetworkBlockedError``: opening
a connection, looking up a host name, sending a datagram, or binding or listening on an address
(ruling R77). The error is an ``OSError``, which is what a library expects from a network that is
down, so it fails the way a missing connection fails, with nothing sent.

Only internet sockets (AF_INET and AF_INET6) are blocked, loopback included. A Unix-domain socket
never leaves the computer, and Qt and the operating system's libraries use them to reach other
processes on it, so those stay open.

The guard also points ``tldextract`` at the public-suffix list that ships in its package. By
default tldextract fetches a fresh list from the internet and keeps a copy under ~/.cache; with the
guard on, that fetch fails and tldextract warns about the "Public Suffix List". Presidio's own
e-mail recognizer calls ``tldextract.extract`` (ours does not), so the replacement is made before
Presidio is used.
"""

from __future__ import annotations

import functools
import socket
from typing import Any, NoReturn

import tldextract

MESSAGE = "The MASK never uses the network."

# The socket methods that start a conversation with another computer, address a message to one,
# or wait for one to call. A method of an internet socket raises; any other family goes through.
_GUARDED_METHODS = ("connect", "connect_ex", "sendto", "bind", "listen")
# The socket module's functions that open a connection or look up a host name.
_BLOCKED_FUNCTIONS = ("create_connection", "getaddrinfo")
_INTERNET_FAMILIES = frozenset({socket.AF_INET, socket.AF_INET6})

_installed = False


class NetworkBlockedError(OSError):
    """Code tried to use the network, which The MASK never does."""


def install_network_guard() -> None:
    """Block the internet for the rest of the process, and make tldextract work offline.

    Calling it again changes nothing. The guard cannot be taken off.
    """
    global _installed
    if _installed:
        return
    for name in _GUARDED_METHODS:
        _guard_method(name)
    for name in _BLOCKED_FUNCTIONS:
        _block_function(name)
    # No address to fetch a list from, so the list in the package is the one used; and no cache
    # folder, so that nothing is written outside the app's data folder (an unwritable cache folder
    # makes tldextract warn about the list too).
    offline = tldextract.TLDExtract(cache_dir=None, suffix_list_urls=(), fallback_to_snapshot=True)
    tldextract.extract = offline  # type: ignore[assignment]  # a callable object for a function
    _installed = True


def _guard_method(name: str) -> None:
    """Make the socket method ``name`` raise for an internet socket and work for any other."""
    original = getattr(socket.socket, name)

    @functools.wraps(original)
    def guarded(self: socket.socket, *args: Any, **kwargs: Any) -> Any:
        if self.family in _INTERNET_FAMILIES:
            raise NetworkBlockedError(MESSAGE)
        return original(self, *args, **kwargs)

    setattr(socket.socket, name, guarded)


def _block_function(name: str) -> None:
    """Make the function ``name`` of the socket module always raise."""

    @functools.wraps(getattr(socket, name))
    def blocked(*args: Any, **kwargs: Any) -> NoReturn:
        raise NetworkBlockedError(MESSAGE)

    setattr(socket, name, blocked)
