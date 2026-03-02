from __future__ import annotations

from pathlib import Path
from typing import Any
from hashlib import sha256
from datetime import datetime, timezone
import json

from .models import JsonStore, Project, Version, now_iso, Task


class ApiError(Exception):
    def __init__(self, code: int, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


class OpenMusicService:
    def __init__(self, data_root: Path | str = "./runtime_data") -> None:
        self.root = Path(data_root)
        self.store = JsonStore(self.root)

    def _project_dir(self, project_id: str, version: str) -> Path:
        path = self.root / "projects" / project_id / version
        path.mkdir(parents=True, exist_ok=True)
        return path

    @staticmethod
    def _ok(data: dict[str, Any]) -> dict[str, Any]:
        return {"code": 0, "message": "ok", "data": data}

    @staticmethod
    def _validate_duration(duration_sec: int) -> None:
        if duration_sec > 60:
            raise ApiError(1002, "duration exceeds 60 seconds")

    @staticmethod
    def _checksum(path: Path) -> str:
        return sha256(path.read_bytes()).hexdigest()

    @staticmethod
    def _write_json(path: Path, content: dict[str, Any]) -> None:
        path.write_text(json.dumps(content, ensure_ascii=False, indent=2), encoding="utf-8")

    def _next_version(self, project: Project | None) -> str:
        if project is None or not project.active_version:
            return "v001"
        index = int(project.active_version[1:]) + 1
        return f"v{index:03d}"

    def compose(self, payload: dict[str, Any]) -> dict[str, Any]:
        required = ["project_id", "title", "style", "mood", "tempo_bpm", "key", "duration_sec", "difficulty", "reference"]
        if any(k not in payload for k in required):
            raise ApiError(1001, "invalid parameters")
        self._validate_duration(int(payload["duration_sec"]))

        project_id = payload["project_id"]
        existing = self.store.get_project(project_id)
        version = self._next_version(existing)

        project = existing or Project(project_id=project_id, title=payload["title"])
        project.updated_at = now_iso()
        project.active_version = version

        version_obj = Version(project_id=project_id, version=version, parent_version=(existing.active_version if existing else None), reason="compose")
        self.store.upsert_version(version_obj)
        self.store.upsert_project(project)

        folder = self._project_dir(project_id, version)
        score = {
            "meta": {
                "time_signature": "4/4",
                "tempo_bpm": payload["tempo_bpm"],
                "key": payload["key"],
                "duration_sec": payload["duration_sec"],
                "style": payload["style"],
            },
            "notes": [
                {"note_id": "n_000001", "bar": 1, "beat": 1.0, "pitch": "A4", "dur": "1/4", "vel": 72, "tie": False},
                {"note_id": "n_000002", "bar": 1, "beat": 2.0, "pitch": "C5", "dur": "1/4", "vel": 72, "tie": False},
            ],
        }
        score_path = folder / "score.json"
        self._write_json(score_path, score)

        musicxml_path = folder / "song.musicxml"
        midi_path = folder / "song.mid"
        musicxml_path.write_text("""<?xml version='1.0' encoding='UTF-8'?><score-partwise version='3.1'></score-partwise>""", encoding="utf-8")
        midi_path.write_bytes(b"MThd\x00\x00\x00\x06\x00\x01\x00\x01\x00\x60MTrk\x00\x00\x00\x04\x00\xff/\x00")

        return self._ok({
            "version": version,
            "score_json": str(score_path),
            "musicxml": str(musicxml_path),
            "midi": str(midi_path),
        })

    def render_audio(self, payload: dict[str, Any]) -> dict[str, Any]:
        for k in ("project_id", "version", "midi_path", "soundfont_path"):
            if k not in payload:
                raise ApiError(1001, "invalid parameters")

        task = self.store.create_task(payload["project_id"], payload["version"], "render_audio")
        task.status = "running"
        task.started_at = now_iso()
        self.store.update_task(task)

        folder = self._project_dir(payload["project_id"], payload["version"])
        wav = folder / "song.wav"
        wav.write_bytes(b"RIFF\x24\x00\x00\x00WAVEfmt ")

        task.status = "success"
        task.ended_at = now_iso()
        self.store.update_task(task)
        return self._ok({"task_id": task.task_id, "wav_path": str(wav)})

    def render_video(self, payload: dict[str, Any]) -> dict[str, Any]:
        for k in ("project_id", "version", "musicxml_path", "wav_path", "highlight_scheme"):
            if k not in payload:
                raise ApiError(1001, "invalid parameters")

        task = self.store.create_task(payload["project_id"], payload["version"], "render_video")
        task.status = "running"
        task.started_at = now_iso()
        self.store.update_task(task)

        folder = self._project_dir(payload["project_id"], payload["version"])
        mp4 = folder / "song.mp4"
        mp4.write_bytes(b"\x00\x00\x00\x18ftypmp42")

        task.status = "success"
        task.ended_at = now_iso()
        self.store.update_task(task)
        return self._ok({"task_id": task.task_id, "mp4_path": str(mp4)})

    def score_edit(self, payload: dict[str, Any]) -> dict[str, Any]:
        for k in ("project_id", "base_version", "edits"):
            if k not in payload:
                raise ApiError(1001, "invalid parameters")

        project = self.store.get_project(payload["project_id"])
        if not project:
            raise ApiError(1001, "project not found")

        new_version = self._next_version(project)
        base_dir = self._project_dir(payload["project_id"], payload["base_version"])
        base_score = base_dir / "score.json"
        if not base_score.exists():
            raise ApiError(1001, "base score not found")

        score = json.loads(base_score.read_text(encoding="utf-8"))
        notes = {n["note_id"]: n for n in score["notes"]}
        for edit in payload["edits"]:
            note = notes.get(edit.get("note_id"))
            if note and edit.get("type") == "pitch_shift":
                note["pitch"] = "C5" if edit.get("semitones", 0) >= 0 else "A4"

        folder = self._project_dir(payload["project_id"], new_version)
        score_path = folder / "score.json"
        self._write_json(score_path, score)
        musicxml = folder / "song.musicxml"
        midi = folder / "song.mid"
        musicxml.write_text("<?xml version='1.0' encoding='UTF-8'?><score-partwise version='3.1'></score-partwise>", encoding="utf-8")
        midi.write_bytes(b"MThd\x00\x00\x00\x06\x00\x01\x00\x01\x00\x60MTrk\x00\x00\x00\x04\x00\xff/\x00")

        self.store.upsert_version(Version(project_id=project.project_id, version=new_version, parent_version=payload["base_version"], reason="manual_edit"))
        project.active_version = new_version
        project.updated_at = now_iso()
        self.store.upsert_project(project)

        return self._ok({"new_version": new_version, "score_json": str(score_path), "musicxml": str(musicxml), "midi": str(midi)})

    def export(self, payload: dict[str, Any]) -> dict[str, Any]:
        for k in ("project_id", "version", "targets"):
            if k not in payload:
                raise ApiError(1001, "invalid parameters")

        folder = self._project_dir(payload["project_id"], payload["version"])
        musicxml = folder / "song.musicxml"
        midi = folder / "song.mid"
        mp4 = folder / "song.mp4"
        missing = [p.name for p in (musicxml, midi, mp4) if not p.exists()]
        if missing:
            raise ApiError(5001, f"missing artifacts: {', '.join(missing)}")

        manifest = {
            "project_id": payload["project_id"],
            "version": payload["version"],
            "exports": {"musicxml": str(musicxml), "midi": str(midi), "mp4": str(mp4)},
            "checksum": {
                "musicxml": self._checksum(musicxml),
                "midi": self._checksum(midi),
                "mp4": self._checksum(mp4),
            },
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        manifest_path = folder / "manifest.json"
        self._write_json(manifest_path, manifest)
        return self._ok({"export_dir": str(folder), "manifest": str(manifest_path)})

    def task_status(self, task_id: str) -> dict[str, Any]:
        task = self.store.get_task(task_id)
        if not task:
            raise ApiError(1001, "task not found")
        return self._ok(task.to_dict())
