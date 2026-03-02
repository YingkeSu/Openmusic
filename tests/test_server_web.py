from __future__ import annotations

import json
import socket
import threading
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

from services.orchestrator import Orchestrator
from services.server import PianoRequestHandler, _create_server_with_fallback


def _http_get(url: str) -> tuple[int, str, bytes]:
    req = urllib.request.Request(url=url, method="GET")
    with urllib.request.urlopen(req, timeout=5) as resp:
        return resp.status, resp.headers.get("Content-Type", ""), resp.read()


def test_web_root_and_web_path_available(tmp_path: Path) -> None:
    handler = PianoRequestHandler
    handler.orchestrator = Orchestrator(root_dir=tmp_path)
    handler.root_dir = tmp_path
    handler.web_dir = Path(__file__).resolve().parent.parent / "app" / "web"

    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    host, port = server.server_address
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    try:
        status_root, ctype_root, body_root = _http_get(f"http://{host}:{port}/")
        assert status_root == 200
        assert "text/html" in ctype_root
        assert b"Piano for AI" in body_root

        status_web, ctype_web, body_web = _http_get(f"http://{host}:{port}/web")
        assert status_web == 200
        assert "text/html" in ctype_web
        assert b"/api/v1/compose" in body_web

        status_health, ctype_health, body_health = _http_get(f"http://{host}:{port}/healthz")
        assert status_health == 200
        assert "application/json" in ctype_health
        payload = json.loads(body_health.decode("utf-8"))
        assert payload["code"] == 0
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def test_server_port_fallback_when_preferred_port_in_use(tmp_path: Path) -> None:
    handler = PianoRequestHandler
    handler.orchestrator = Orchestrator(root_dir=tmp_path)
    handler.root_dir = tmp_path
    handler.web_dir = Path(__file__).resolve().parent.parent / "app" / "web"

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as busy:
        busy.bind(("127.0.0.1", 0))
        busy.listen(1)
        busy_port = busy.getsockname()[1]

        server = _create_server_with_fallback("127.0.0.1", busy_port, handler)
        try:
            assert server.server_port != busy_port
        finally:
            server.server_close()
