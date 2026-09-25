"""Serve the fixture pages over local HTTP so the browser loads them like real sites."""

from __future__ import annotations

import functools
import http.server
import socketserver
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

REPO_ROOT = Path(__file__).resolve().parents[3]
FIXTURES_DIR = REPO_ROOT / "eval" / "fixtures"


class _QuietHandler(http.server.SimpleHTTPRequestHandler):
    def log_message(self, format, *args):  # noqa: A002 - keep test output clean
        pass


class _Server(socketserver.ThreadingTCPServer):
    daemon_threads = True
    allow_reuse_address = True


@contextmanager
def serve_directory(directory: Path = FIXTURES_DIR) -> Iterator[str]:
    """Yield a base URL like 'http://127.0.0.1:54321' serving `directory`."""
    handler = functools.partial(_QuietHandler, directory=str(directory))
    server = _Server(("127.0.0.1", 0), handler)  # port 0 = pick any free port
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}"
    finally:
        server.shutdown()
        server.server_close()
