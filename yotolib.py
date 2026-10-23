"""Start YotoLib and open it in a browser."""

import os
import socket
import sys
import threading
import time
import webbrowser

DEFAULT_HOST = "127.0.0.1"
PORT_START = 8765
PORT_TRIES = 20


def configured_host():
    return os.environ.get("YOTOLIB_HOST", "").strip() or DEFAULT_HOST


def configured_port():
    """Fixed port from YOTOLIB_PORT, or None to pick a free port from 8765."""
    raw = os.environ.get("YOTOLIB_PORT", "").strip()
    if not raw:
        return None
    try:
        port = int(raw)
    except ValueError as ex:
        raise RuntimeError("YOTOLIB_PORT must be a port number.") from ex
    if port < 1 or port > 65535:
        raise RuntimeError("YOTOLIB_PORT must be between 1 and 65535.")
    return port


def open_browser_enabled():
    raw = os.environ.get("YOTOLIB_OPEN_BROWSER", "").strip().lower()
    if not raw:
        return True
    return raw in {"1", "true", "yes", "on"}


def pick_port(host):
    for port in range(PORT_START, PORT_START + PORT_TRIES):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            try:
                sock.bind((host, port))
            except OSError:
                continue
            return port
    raise RuntimeError(
        f"No free port between {PORT_START} and {PORT_START + PORT_TRIES - 1}."
    )


def main():
    import uvicorn

    from server import app

    host = configured_host()
    port = configured_port()
    if port is None:
        port = pick_port(host)
    url = f"http://{host}:{port}"
    print(f"YotoLib at {url}")
    print("Close this window to stop the app.")

    if open_browser_enabled():
        def open_browser():
            time.sleep(0.7)
            webbrowser.open(url)

        threading.Thread(target=open_browser, daemon=True).start()
    uvicorn.run(app, host=host, port=port, log_level="info")


if __name__ == "__main__":
    import multiprocessing

    multiprocessing.freeze_support()
    try:
        main()
    except KeyboardInterrupt:
        sys.exit(0)
