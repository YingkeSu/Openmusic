from __future__ import annotations

import argparse
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

from .orchestrator import Orchestrator, handle_call


class PianoRequestHandler(BaseHTTPRequestHandler):
    orchestrator: Orchestrator

    def do_POST(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        payload = self._read_json_body()

        routes = {
            "/api/v1/compose": self.orchestrator.compose,
            "/api/v1/render/audio": self.orchestrator.render_audio,
            "/api/v1/render/video": self.orchestrator.render_video,
            "/api/v1/score/edit": self.orchestrator.edit_score,
            "/api/v1/score/rollback": self.orchestrator.rollback,
            "/api/v1/export": self.orchestrator.export,
        }

        handler = routes.get(parsed.path)
        if handler is None:
            self._send_json(404, {"code": 404, "message": "not found", "data": {}})
            return

        response = handle_call(handler, payload)
        status = 200 if response["code"] == 0 else 400
        self._send_json(status, response)

    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        if parsed.path.startswith("/api/v1/tasks/"):
            task_id = parsed.path.removeprefix("/api/v1/tasks/")
            response = handle_call(lambda _: self.orchestrator.get_task(task_id), {})
            status = 200 if response["code"] == 0 else 404
            self._send_json(status, response)
            return

        if parsed.path == "/healthz":
            self._send_json(200, {"code": 0, "message": "ok", "data": {"status": "healthy"}})
            return

        self._send_json(404, {"code": 404, "message": "not found", "data": {}})

    def log_message(self, format: str, *args) -> None:  # noqa: A003
        return

    def _read_json_body(self) -> dict:
        content_len = int(self.headers.get("Content-Length", "0"))
        if content_len <= 0:
            return {}
        raw = self.rfile.read(content_len)
        try:
            return json.loads(raw.decode("utf-8"))
        except Exception:
            return {}

    def _send_json(self, status: int, payload: dict) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def run_server(host: str, port: int, root_dir: Path) -> None:
    orchestrator = Orchestrator(root_dir=root_dir)
    PianoRequestHandler.orchestrator = orchestrator
    server = ThreadingHTTPServer((host, port), PianoRequestHandler)
    print(f"Piano service running on http://{host}:{port}")
    print(f"Workspace root: {root_dir}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Piano for AI local service")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--root-dir", default=str(Path(__file__).resolve().parent.parent))
    args = parser.parse_args()

    run_server(args.host, args.port, Path(args.root_dir).resolve())


if __name__ == "__main__":
    main()
