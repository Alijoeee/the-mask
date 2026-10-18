"""Starts The MASK: ``uv run python -m themask``.

For now this only puts the safeguards in place and prints the name and version; Task 20 replaces
it with the window.
"""

from themask.about import APP_NAME, VERSION
from themask.logging_setup import setup_logging
from themask.netguard import install_network_guard


def main() -> None:
    """Block the network, start the log, say which version this is."""
    install_network_guard()
    setup_logging()
    print(f"{APP_NAME} {VERSION}")


if __name__ == "__main__":
    main()
