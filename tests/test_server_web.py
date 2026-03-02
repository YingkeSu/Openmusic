from __future__ import annotations

import json
import socket
import threading
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

from services.orchestrator import Orchestrator
from services.utils import dump_json, load_json
from services.server import PianoRequestHandler, _create_server_with_fallback


def _http_get(url: str) -> tuple[int, str, bytes]:
    req = urllib.request.Request(url=url, method="GET")
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            return resp.status, resp.headers.get("Content-Type", ""), resp.read()
    except urllib.error.HTTPError as exc:
        return exc.code, exc.headers.get("Content-Type", ""), exc.read()


def _http_post_json(url: str, payload: dict) -> tuple[int, str, bytes]:
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        url=url,
        data=body,
        method="POST",
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            return resp.status, resp.headers.get("Content-Type", ""), resp.read()
    except urllib.error.HTTPError as exc:
        return exc.code, exc.headers.get("Content-Type", ""), exc.read()


def test_web_root_and_web_path_available(tmp_path: Path) -> None:
    handler = PianoRequestHandler
    orchestrator = Orchestrator(root_dir=tmp_path)
    handler.orchestrator = orchestrator
    handler.root_dir = tmp_path
    handler.web_dir = Path(__file__).resolve().parent.parent / "app" / "web"
    (tmp_path / "projects" / "x" / "v001").mkdir(parents=True, exist_ok=True)
    (tmp_path / "projects" / "x" / "v001" / "song.mp4").write_bytes(b"abc")
    orchestrator.compose(
        {
            "project_id": "web_test_project",
            "title": "web test",
            "style": "ancient_cn",
            "mood": "calm",
            "tempo_bpm": 88,
            "key": "D",
            "duration_sec": 8,
            "difficulty": "medium",
            "reference": "test",
            "compose_mode": "rule",
        }
    )
    dump_json(
        tmp_path / "projects" / "web_test_project" / "v001" / "llm_output.json",
        {"project_id": "web_test_project", "version": "v001", "llm": {"raw_content": "{}"}},
    )
    dump_json(
        tmp_path / "assets" / "reference_scores" / "senbonzakura.score.json",
        load_json(tmp_path / "projects" / "web_test_project" / "v001" / "score.json"),
    )

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

        status_file, ctype_file, body_file = _http_get(
            f"http://{host}:{port}/projects/x/v001/song.mp4"
        )
        assert status_file == 200
        assert body_file == b"abc"

        status_forbid, _, _ = _http_get(f"http://{host}:{port}/projects/../.env")
        assert status_forbid == 403

        status_projects, _, body_projects = _http_get(f"http://{host}:{port}/api/v1/projects")
        assert status_projects == 200
        payload_projects = json.loads(body_projects.decode("utf-8"))
        assert payload_projects["code"] == 0
        project_ids = [item["project_id"] for item in payload_projects["data"]["projects"]]
        assert "web_test_project" in project_ids

        status_project, _, body_project = _http_get(
            f"http://{host}:{port}/api/v1/projects/web_test_project"
        )
        assert status_project == 200
        payload_project = json.loads(body_project.decode("utf-8"))
        assert payload_project["code"] == 0
        assert payload_project["data"]["project"]["project_id"] == "web_test_project"

        status_score, _, body_score = _http_get(
            f"http://{host}:{port}/api/v1/projects/web_test_project/score/v001"
        )
        assert status_score == 200
        payload_score = json.loads(body_score.decode("utf-8"))
        assert payload_score["code"] == 0
        assert payload_score["data"]["score"]["meta"]["title"] == "web test"

        status_llm, _, body_llm = _http_get(
            f"http://{host}:{port}/api/v1/projects/web_test_project/llm/v001"
        )
        assert status_llm == 200
        payload_llm = json.loads(body_llm.decode("utf-8"))
        assert payload_llm["code"] == 0
        assert payload_llm["data"]["llm_output"]["project_id"] == "web_test_project"

        status_eval, _, body_eval = _http_post_json(
            f"http://{host}:{port}/api/v1/evaluate/similarity",
            {
                "project_id": "web_test_project",
                "version": "v001",
                "target_song": "senbonzakura",
                "threshold": 95.0,
            },
        )
        assert status_eval == 200
        payload_eval = json.loads(body_eval.decode("utf-8"))
        assert payload_eval["code"] == 0
        assert payload_eval["data"]["pass"] is True
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
