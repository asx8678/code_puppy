"""Entry point for running the FastAPI server."""

import logging
import threading
import webbrowser

import uvicorn

from code_puppy.api.app import create_app

logger = logging.getLogger(__name__)

app = create_app()

_LOCALHOST_HOSTS = frozenset({"127.0.0.1", "::1", "localhost"})


def main(
    host: str = "127.0.0.1",
    port: int = 8765,
    open_browser: bool = False,
    allow_external: bool = False,
) -> None:
    """Run the FastAPI server.

    Args:
        host: The host address to bind to. Defaults to localhost (127.0.0.1).
            Binding to 0.0.0.0 or any non-localhost address exposes the API
            — including agent control and file-mutation endpoints — to the
            network.  This requires an explicit decision via *allow_external*
            or the ``CODE_PUPPY_ALLOW_EXTERNAL`` environment variable; the
            default is localhost-only.
        port: The port number to listen on. Defaults to 8765.
        open_browser: Open the integrated dashboard in the default browser.
        allow_external: Must be True to bind to a non-localhost address.
            If False (default) and *host* is not a localhost address, the
            server will refuse to start.
    """
    import os

    # Allow environment variable override for external access
    if not allow_external:
        allow_external = os.getenv("CODE_PUPPY_ALLOW_EXTERNAL", "").strip().lower() in (
            "1",
            "true",
            "yes",
        )

    if host not in _LOCALHOST_HOSTS:
        if not allow_external:
            raise SystemExit(
                f"Refusing to bind to {host} without explicit external access "
                f"permission.  Pass allow_external=True or set "
                f"CODE_PUPPY_ALLOW_EXTERNAL=1 to enable network exposure.\n"
                f"⚠️  The API controls an AI agent with file system access — "
                f"network exposure requires an informed decision."
            )
        logger.warning(
            "⚠️  Binding to %s — the API (including agent control and file-mutation "
            "endpoints) will be reachable from the network.  Ensure this is "
            "intentional and that appropriate access controls are in place.",
            host,
        )

    if open_browser:
        browser_host = "127.0.0.1" if host in {"0.0.0.0", "::"} else host
        url = f"http://{browser_host}:{port}/dashboard"
        threading.Timer(0.8, lambda: webbrowser.open(url)).start()
    uvicorn.run(app, host=host, port=port)


if __name__ == "__main__":
    main()
