from __future__ import annotations

import argparse
import json
import mimetypes
import socket
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

from .orchestrator import Orchestrator, handle_call


class PianoRequestHandler(BaseHTTPRequestHandler):
    orchestrator: Orchestrator
    root_dir: Path
    web_dir: Path

    def do_OPTIONS(self) -> None:  # noqa: N802
        self.send_response(204)
        self._send_cors_headers()
        self.end_headers()

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
            "/api/v1/evaluate/similarity": self.orchestrator.evaluate_similarity,
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
        if parsed.path in {"/", "/web", "/web/"}:
            self._serve_web_index()
            return

        if parsed.path == "/web/index.html":
            self._serve_web_index()
            return

        if parsed.path.startswith("/projects/"):
            self._serve_workspace_file(
                relative_path=parsed.path.removeprefix("/"),
                allowed_root=self.root_dir / "projects",
            )
            return

        if parsed.path.startswith("/assets/"):
            self._serve_workspace_file(
                relative_path=parsed.path.removeprefix("/"),
                allowed_root=self.root_dir / "assets",
            )
            return

        if parsed.path.startswith("/api/v1/tasks/"):
            task_id = parsed.path.removeprefix("/api/v1/tasks/")
            response = handle_call(lambda _: self.orchestrator.get_task(task_id), {})
            status = 200 if response["code"] == 0 else 404
            self._send_json(status, response)
            return

        if parsed.path == "/api/v1/projects":
            response = handle_call(lambda _: self.orchestrator.list_projects(), {})
            status = 200 if response["code"] == 0 else 400
            self._send_json(status, response)
            return

        if parsed.path.startswith("/api/v1/projects/"):
            segments = [seg for seg in parsed.path.split("/") if seg]
            # /api/v1/projects/{project_id}
            if len(segments) == 4:
                project_id = segments[3]
                response = handle_call(lambda _: self.orchestrator.get_project(project_id), {})
                status = 200 if response["code"] == 0 else 404
                self._send_json(status, response)
                return
            # /api/v1/projects/{project_id}/score/{version}
            if len(segments) == 6 and segments[4] == "score":
                project_id = segments[3]
                version = segments[5]
                response = handle_call(lambda _: self.orchestrator.get_score(project_id, version), {})
                status = 200 if response["code"] == 0 else 404
                self._send_json(status, response)
                return
            # /api/v1/projects/{project_id}/llm/{version}
            if len(segments) == 6 and segments[4] == "llm":
                project_id = segments[3]
                version = segments[5]
                response = handle_call(lambda _: self.orchestrator.get_llm_output(project_id, version), {})
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
        self._send_cors_headers()
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _serve_web_index(self) -> None:
        html_path = self.web_dir / "index.html"
        if not html_path.exists():
            self._send_json(
                500,
                {
                    "code": 500,
                    "message": f"web entry not found: {html_path}",
                    "data": {},
                },
            )
            return
        self._send_html(200, html_path.read_text(encoding="utf-8"))

    def _send_html(self, status: int, html: str) -> None:
        body = html.encode("utf-8")
        self.send_response(status)
        self._send_cors_headers()
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_cors_headers(self) -> None:
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization")

    def _serve_workspace_file(self, relative_path: str, allowed_root: Path) -> None:
        requested = (self.root_dir / relative_path).resolve()
        try:
            requested.relative_to(allowed_root.resolve())
        except ValueError:
            self._send_json(403, {"code": 403, "message": "forbidden", "data": {}})
            return

        if not requested.exists() or not requested.is_file():
            self._send_json(404, {"code": 404, "message": "not found", "data": {}})
            return

        ctype, _ = mimetypes.guess_type(str(requested))
        content_type = ctype or "application/octet-stream"
        body = requested.read_bytes()
        self.send_response(200)
        self._send_cors_headers()
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def run_server(host: str, port: int, root_dir: Path) -> None:
    orchestrator = Orchestrator(root_dir=root_dir)
    PianoRequestHandler.orchestrator = orchestrator
    PianoRequestHandler.root_dir = root_dir
    PianoRequestHandler.web_dir = root_dir / "app" / "web"
    server = _create_server_with_fallback(host, port, PianoRequestHandler)
    actual_port = server.server_port
    print(f"Piano service running on http://{host}:{actual_port}")
    print(f"Web entry: http://{host}:{actual_port}/")
    print(f"Workspace root: {root_dir}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


def _create_server_with_fallback(
    host: str,
    preferred_port: int,
    handler: type[BaseHTTPRequestHandler],
) -> ThreadingHTTPServer:
    try:
        return ThreadingHTTPServer((host, preferred_port), handler)
    except OSError as exc:
        if exc.errno not in {48, 98}:
            raise
    # Port conflict: fallback to a random free port.
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind((host, 0))
        fallback_port = sock.getsockname()[1]
    print(
        f"[warn] port {preferred_port} is in use, switched to available port {fallback_port}",
    )
    return ThreadingHTTPServer((host, fallback_port), handler)


def main() -> None:
    parser = argparse.ArgumentParser(description="Piano for AI local service")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--root-dir", default=str(Path(__file__).resolve().parent.parent))
    args = parser.parse_args()

    run_server(args.host, args.port, Path(args.root_dir).resolve())


if __name__ == "__main__":
    main()
