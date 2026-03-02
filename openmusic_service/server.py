from __future__ import annotations

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from urllib.parse import urlparse

from .service import OpenMusicService, ApiError


class ApiHandler(BaseHTTPRequestHandler):
    service = OpenMusicService()

    def _write(self, status: int, payload: dict) -> None:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _read_json(self) -> dict:
        length = int(self.headers.get("Content-Length", "0"))
        if length == 0:
            return {}
        return json.loads(self.rfile.read(length).decode("utf-8"))

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        body = self._read_json()
        try:
            if parsed.path == "/api/v1/compose":
                self._write(200, self.service.compose(body))
            elif parsed.path == "/api/v1/render/audio":
                self._write(200, self.service.render_audio(body))
            elif parsed.path == "/api/v1/render/video":
                self._write(200, self.service.render_video(body))
            elif parsed.path == "/api/v1/score/edit":
                self._write(200, self.service.score_edit(body))
            elif parsed.path == "/api/v1/export":
                self._write(200, self.service.export(body))
            else:
                self._write(404, {"code": 404, "message": "not found", "data": {}})
        except ApiError as e:
            self._write(400, {"code": e.code, "message": e.message, "data": {}})
        except Exception as e:  # noqa: BLE001
            self._write(500, {"code": 5000, "message": str(e), "data": {}})

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        try:
            if parsed.path.startswith("/api/v1/tasks/"):
                task_id = parsed.path.split("/")[-1]
                self._write(200, self.service.task_status(task_id))
            else:
                self._write(404, {"code": 404, "message": "not found", "data": {}})
        except ApiError as e:
            self._write(404, {"code": e.code, "message": e.message, "data": {}})


def run(host: str = "127.0.0.1", port: int = 18080) -> None:
    server = ThreadingHTTPServer((host, port), ApiHandler)
    print(f"OpenMusic MVP service started on http://{host}:{port}")
    server.serve_forever()


if __name__ == "__main__":
    run()
