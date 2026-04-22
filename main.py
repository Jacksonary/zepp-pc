"""
Zepp PC Manager entry point.

Starts FastAPI server in a background thread,
then opens pywebview window pointing to it.
"""

import logging
import threading
import time
import urllib.request

import uvicorn
import webview

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

HOST = "127.0.0.1"
PORT = 8765


def run_server():
    """Run FastAPI server in a background thread."""
    config = uvicorn.Config(
        "src.server.main:app",
        host=HOST,
        port=PORT,
        log_level="info",
    )
    server = uvicorn.Server(config)
    server.run()


def main():
    """Launch the desktop application."""
    logger.info("Starting Zepp PC Manager...")

    # Start FastAPI in background thread
    server_thread = threading.Thread(target=run_server, daemon=True)
    server_thread.start()

    # Wait for server to be ready
    for _ in range(20):
        try:
            urllib.request.urlopen(f"http://{HOST}:{PORT}/api/", timeout=1)
            break
        except Exception:
            time.sleep(0.25)

    url = f"http://{HOST}:{PORT}/api/"
    logger.info(f"Server ready at {url}")

    # Create pywebview window
    window = webview.create_window(
        title="Zepp PC Manager",
        url=url,
        width=900,
        height=700,
        resizable=True,
        min_size=(700, 500),
    )

    # Start pywebview (blocks until window closes)
    webview.start(debug=False)


if __name__ == "__main__":
    main()
