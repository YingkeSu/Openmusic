from __future__ import annotations

import copy
import traceback
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from threading import Lock
from typing import Any, Callable

from .ai_composer import AIComposer
from .ai_config import LLMConfigRegistry, resolve_llm_runtime
from .audio_renderer import AudioRenderer
from .compiler import Compiler
from .composer import Composer
from .constants import (
    DEFAULT_SOUNDFONT,
    ERROR_COMPOSE_FAILED,
    ERROR_DURATION_EXCEEDED,
    ERROR_INVALID_PARAMS,
    ERROR_RENDER_AUDIO_FAILED,
    ERROR_RENDER_VIDEO_FAILED,
    MAX_DURATION_SEC,
    MAX_LLM_RETRY,
    MAX_RENDER_RETRY,
)
from .errors import ServiceError
from .exporter import Exporter
from .models import Score, TaskRecord
from .storage import Storage
from .utils import dump_json, load_json, log_line, to_relpath, transpose_pitch, utc_now_iso
from .video_renderer import VideoRenderer


@dataclass
class TaskStore:
    root_dir: Path
    tasks: dict[str, TaskRecord] = field(default_factory=dict)
    _lock: Lock = field(default_factory=Lock)

    def create(self, project_id: str, version: str, stage: str) -> TaskRecord:
        record = TaskRecord(
            task_id=str(uuid.uuid4()),
            project_id=project_id,
            version=version,
            stage=stage,
            status="queued",
            started_at=utc_now_iso(),
        )
        with self._lock:
            self.tasks[record.task_id] = record
        self._persist(record)
        return record

    def running(self, task_id: str, version: str = "") -> None:
        with self._lock:
            record = self.tasks[task_id]
            record.status = "running"
            if version:
                record.version = version
        self._persist(self.tasks[task_id])

    def success(self, task_id: str, version: str = "") -> None:
        with self._lock:
            record = self.tasks[task_id]
            record.status = "success"
            if version:
                record.version = version
            record.ended_at = utc_now_iso()
        self._persist(self.tasks[task_id])

    def failed(self, task_id: str, message: str, version: str = "") -> None:
        with self._lock:
            record = self.tasks[task_id]
            record.status = "failed"
            record.error = message
            if version:
                record.version = version
            record.ended_at = utc_now_iso()
        self._persist(self.tasks[task_id])

    def get(self, task_id: str) -> TaskRecord | None:
        with self._lock:
            return self.tasks.get(task_id)

    def _persist(self, record: TaskRecord) -> None:
        path = self.root_dir / "logs" / "tasks" / f"{record.task_id}.log"
        line = (
            f"task_id={record.task_id} project_id={record.project_id} version={record.version} "
            f"stage={record.stage} status={record.status} error={record.error}"
        )
        log_line(path, line)


@dataclass
class Orchestrator:
    root_dir: Path

    def __post_init__(self) -> None:
        self.root_dir = self.root_dir.resolve()
        self.storage = Storage(self.root_dir)
        self.composer = Composer()
        self.compiler = Compiler()
        self.audio_renderer = AudioRenderer()
        self.video_renderer = VideoRenderer()
        self.exporter = Exporter(self.root_dir)
        self.tasks = TaskStore(self.root_dir)
        registry_path = self.root_dir / "services" / "config" / "llm_providers.json"
        if not registry_path.exists():
            registry_path = Path(__file__).resolve().parent / "config" / "llm_providers.json"
        self.ai_registry = LLMConfigRegistry.load(registry_path)
        self.ai_composer = AIComposer()

    def compose(self, payload: dict[str, Any]) -> dict[str, Any]:
        self._require_fields(
            payload,
            [
                "project_id",
                "title",
                "style",
                "mood",
                "tempo_bpm",
                "key",
                "duration_sec",
                "difficulty",
                "reference",
            ],
        )
        project_id = str(payload["project_id"]).strip()
        if not project_id:
            raise ServiceError(ERROR_INVALID_PARAMS, "project_id is required")

        duration_sec = int(payload["duration_sec"])
        if duration_sec > MAX_DURATION_SEC:
            raise ServiceError(ERROR_DURATION_EXCEEDED, f"duration_sec exceeds {MAX_DURATION_SEC}")
        if duration_sec <= 0:
            raise ServiceError(ERROR_INVALID_PARAMS, "duration_sec must be positive")

        intent = dict(payload)
        if intent.get("style") != "ancient_cn":
            intent["style"] = "custom"
        compose_mode = str(payload.get("compose_mode", "auto")).strip().lower() or "auto"
        if compose_mode not in {"auto", "ai", "rule"}:
            raise ServiceError(
                ERROR_INVALID_PARAMS,
                "compose_mode must be one of: auto | ai | rule",
            )

        task = self.tasks.create(project_id, "", "compose")
        self.tasks.running(task.task_id)

        score: Score | None = None
        compose_error = ""
        compose_engine = "rule"
        ai_runtime = resolve_llm_runtime(self.root_dir, payload, self.ai_registry)
        ai_requested = compose_mode == "ai" or (compose_mode == "auto" and ai_runtime.enabled)

        for attempt in range(1, MAX_LLM_RETRY + 1):
            try:
                if ai_requested:
                    score = self.ai_composer.compose(intent, ai_runtime)
                    compose_engine = "ai"
                else:
                    score = self.composer.compose(intent)
                    compose_engine = "rule"
                break
            except Exception as exc:
                compose_error = f"compose attempt {attempt} failed: {exc}"
                self._log_task(task.task_id, compose_error)
                if ai_requested and compose_mode == "auto":
                    self._log_task(task.task_id, "fallback to rule composer in auto mode")
                    ai_requested = False

        if score is None:
            self.tasks.failed(task.task_id, compose_error)
            raise ServiceError(ERROR_COMPOSE_FAILED, compose_error)

        try:
            version = self.storage.create_version(project_id, reason="compose", title=intent["title"])
            self.storage.save_score(project_id, version, score.to_dict())

            musicxml_path = self.storage.musicxml_path(project_id, version)
            midi_path = self.storage.midi_path(project_id, version)
            self.compiler.compile(score, musicxml_path, midi_path)
        except ServiceError as exc:
            self.tasks.failed(task.task_id, str(exc))
            raise
        except Exception as exc:
            self.tasks.failed(task.task_id, str(exc))
            raise ServiceError(ERROR_COMPOSE_FAILED, str(exc)) from exc

        self.tasks.success(task.task_id, version)
        return {
            "task_id": task.task_id,
            "version": version,
            "compose_engine": compose_engine,
            "ai_provider": ai_runtime.provider_id if compose_engine == "ai" else "",
            "ai_model": ai_runtime.model if compose_engine == "ai" else "",
            "score_json": to_relpath(self.storage.score_path(project_id, version), self.root_dir),
            "musicxml": to_relpath(musicxml_path, self.root_dir),
            "midi": to_relpath(midi_path, self.root_dir),
        }

    def render_audio(self, payload: dict[str, Any]) -> dict[str, Any]:
        self._require_fields(payload, ["project_id", "version", "midi_path", "soundfont_path"])
        project_id = str(payload["project_id"]).strip()
        version = str(payload["version"]).strip()
        task = self.tasks.create(project_id, version, "render_audio")
        self.tasks.running(task.task_id, version)

        midi_path = self._resolve_local_path(str(payload["midi_path"]))
        soundfont_path = self._resolve_local_path(str(payload.get("soundfont_path") or DEFAULT_SOUNDFONT))
        wav_path = self.storage.wav_path(project_id, version)

        if not midi_path.exists():
            message = f"midi not found: {midi_path}"
            self.tasks.failed(task.task_id, message, version)
            raise ServiceError(ERROR_RENDER_AUDIO_FAILED, message)

        score = self._load_score(project_id, version)

        error_text = ""
        for attempt in range(1, MAX_RENDER_RETRY + 1):
            try:
                self.audio_renderer.render(score, wav_path, soundfont_path)
                self._log_render(task.task_id, f"audio render success at attempt {attempt}: {wav_path}")
                self.tasks.success(task.task_id, version)
                return {
                    "task_id": task.task_id,
                    "wav_path": to_relpath(wav_path, self.root_dir),
                }
            except Exception as exc:
                error_text = f"audio render attempt {attempt} failed: {exc}"
                self._log_render(task.task_id, error_text)

        self.tasks.failed(task.task_id, error_text, version)
        raise ServiceError(ERROR_RENDER_AUDIO_FAILED, error_text)

    def render_video(self, payload: dict[str, Any]) -> dict[str, Any]:
        self._require_fields(payload, ["project_id", "version", "musicxml_path", "wav_path"])
        project_id = str(payload["project_id"]).strip()
        version = str(payload["version"]).strip()
        task = self.tasks.create(project_id, version, "render_video")
        self.tasks.running(task.task_id, version)

        musicxml_path = self._resolve_local_path(str(payload["musicxml_path"]))
        wav_path = self._resolve_local_path(str(payload["wav_path"]))
        mp4_path = self.storage.mp4_path(project_id, version)

        if not musicxml_path.exists():
            message = f"musicxml not found: {musicxml_path}"
            self.tasks.failed(task.task_id, message, version)
            raise ServiceError(ERROR_RENDER_VIDEO_FAILED, message)
        if not wav_path.exists():
            message = f"wav not found: {wav_path}"
            self.tasks.failed(task.task_id, message, version)
            raise ServiceError(ERROR_RENDER_VIDEO_FAILED, message)

        score = self._load_score(project_id, version)
        highlight = payload.get("highlight_scheme") or {}

        error_text = ""
        for attempt in range(1, MAX_RENDER_RETRY + 1):
            try:
                result = self.video_renderer.render(
                    score,
                    wav_path,
                    mp4_path,
                    played_color=str(highlight.get("played", "#000000")),
                    unplayed_color=str(highlight.get("unplayed", "#C8C8C8")),
                )
                self._log_render(
                    task.task_id,
                    f"video render success at attempt {attempt}: {mp4_path} mode={result.mode}",
                )
                self.tasks.success(task.task_id, version)
                return {
                    "task_id": task.task_id,
                    "mp4_path": to_relpath(result.mp4_path, self.root_dir),
                    "sync_delta_ms": result.sync_delta_ms,
                    "render_mode": result.mode,
                }
            except Exception as exc:
                error_text = f"video render attempt {attempt} failed: {exc}"
                self._log_render(task.task_id, error_text)

        self.tasks.failed(task.task_id, error_text, version)
        raise ServiceError(ERROR_RENDER_VIDEO_FAILED, error_text)

    def edit_score(self, payload: dict[str, Any]) -> dict[str, Any]:
        self._require_fields(payload, ["project_id", "base_version", "edits"])
        project_id = str(payload["project_id"]).strip()
        base_version = str(payload["base_version"]).strip()
        edits = payload["edits"]
        if not isinstance(edits, list) or not edits:
            raise ServiceError(ERROR_INVALID_PARAMS, "edits must be a non-empty list")

        task = self.tasks.create(project_id, base_version, "edit")
        self.tasks.running(task.task_id, base_version)

        score_dict = self.storage.load_score(project_id, base_version)
        updated_score = copy.deepcopy(score_dict)
        notes = {n["note_id"]: n for n in updated_score.get("notes", [])}

        for edit in edits:
            note_id = str(edit.get("note_id", ""))
            edit_type = str(edit.get("type", ""))
            if note_id not in notes:
                message = f"note not found: {note_id}"
                self.tasks.failed(task.task_id, message, base_version)
                raise ServiceError(ERROR_INVALID_PARAMS, message)
            if edit_type == "pitch_shift":
                semitones = int(edit.get("semitones", 0))
                notes[note_id]["pitch"] = transpose_pitch(notes[note_id]["pitch"], semitones)
            else:
                message = f"unsupported edit type: {edit_type}"
                self.tasks.failed(task.task_id, message, base_version)
                raise ServiceError(ERROR_INVALID_PARAMS, message)

        try:
            score = Score.from_dict(updated_score)
            self.compiler.validate_score(score)
            new_version = self.storage.create_version(
                project_id,
                reason="manual_edit",
                parent_version=base_version,
            )
            self.storage.save_score(project_id, new_version, score.to_dict())

            musicxml_path = self.storage.musicxml_path(project_id, new_version)
            midi_path = self.storage.midi_path(project_id, new_version)
            self.compiler.compile(score, musicxml_path, midi_path)
        except ServiceError as exc:
            self.tasks.failed(task.task_id, str(exc), base_version)
            raise
        except Exception as exc:
            self.tasks.failed(task.task_id, str(exc), base_version)
            raise ServiceError(ERROR_INVALID_PARAMS, str(exc)) from exc

        self.tasks.success(task.task_id, new_version)
        return {
            "task_id": task.task_id,
            "new_version": new_version,
            "score_json": to_relpath(self.storage.score_path(project_id, new_version), self.root_dir),
            "musicxml": to_relpath(musicxml_path, self.root_dir),
            "midi": to_relpath(midi_path, self.root_dir),
        }

    def rollback(self, payload: dict[str, Any]) -> dict[str, Any]:
        self._require_fields(payload, ["project_id", "target_version"])
        project_id = str(payload["project_id"]).strip()
        target_version = str(payload["target_version"]).strip()

        task = self.tasks.create(project_id, target_version, "rollback")
        self.tasks.running(task.task_id, target_version)

        try:
            target_score = self.storage.load_score(project_id, target_version)
            score = Score.from_dict(target_score)
            self.compiler.validate_score(score)

            new_version = self.storage.create_version(
                project_id,
                reason="rollback",
                parent_version=target_version,
            )
            self.storage.save_score(project_id, new_version, score.to_dict())

            musicxml_path = self.storage.musicxml_path(project_id, new_version)
            midi_path = self.storage.midi_path(project_id, new_version)
            self.compiler.compile(score, musicxml_path, midi_path)

            # Reuse existing rendered artifacts if present.
            self.storage.copy_if_exists(
                self.storage.wav_path(project_id, target_version),
                self.storage.wav_path(project_id, new_version),
            )
            self.storage.copy_if_exists(
                self.storage.mp4_path(project_id, target_version),
                self.storage.mp4_path(project_id, new_version),
            )
        except Exception as exc:
            self.tasks.failed(task.task_id, str(exc), target_version)
            raise ServiceError(ERROR_INVALID_PARAMS, str(exc)) from exc

        self.tasks.success(task.task_id, new_version)
        return {
            "task_id": task.task_id,
            "new_version": new_version,
            "score_json": to_relpath(self.storage.score_path(project_id, new_version), self.root_dir),
            "musicxml": to_relpath(musicxml_path, self.root_dir),
            "midi": to_relpath(midi_path, self.root_dir),
        }

    def export(self, payload: dict[str, Any]) -> dict[str, Any]:
        self._require_fields(payload, ["project_id", "version", "targets"])
        project_id = str(payload["project_id"]).strip()
        version = str(payload["version"]).strip()
        targets = payload.get("targets")
        if not isinstance(targets, list) or not targets:
            raise ServiceError(ERROR_INVALID_PARAMS, "targets must be a non-empty list")

        task = self.tasks.create(project_id, version, "export")
        self.tasks.running(task.task_id, version)

        try:
            version_dir = self.storage.version_dir(project_id, version)
            export_dir = self.storage.exports_dir(project_id, version)
            manifest_path = self.storage.manifest_path(project_id, version)
            out_dir, out_manifest = self.exporter.export(
                project_id=project_id,
                version=version,
                version_dir=version_dir,
                export_dir=export_dir,
                manifest_path=manifest_path,
                targets=[str(target) for target in targets],
            )
            self._log_export(task.task_id, f"export success: {out_dir}")
        except ServiceError as exc:
            self.tasks.failed(task.task_id, str(exc), version)
            raise
        except Exception as exc:
            self.tasks.failed(task.task_id, str(exc), version)
            raise ServiceError(ERROR_INVALID_PARAMS, str(exc)) from exc

        self.tasks.success(task.task_id, version)
        return {
            "task_id": task.task_id,
            "export_dir": to_relpath(out_dir, self.root_dir),
            "manifest_path": to_relpath(out_manifest, self.root_dir),
        }

    def get_task(self, task_id: str) -> dict[str, Any]:
        record = self.tasks.get(task_id)
        if record is None:
            raise ServiceError(ERROR_INVALID_PARAMS, f"task not found: {task_id}")
        return record.to_dict()

    def _require_fields(self, payload: dict[str, Any], fields: list[str]) -> None:
        missing = [field for field in fields if field not in payload]
        if missing:
            raise ServiceError(ERROR_INVALID_PARAMS, f"missing required fields: {missing}")

    def _load_score(self, project_id: str, version: str) -> Score:
        score_path = self.storage.score_path(project_id, version)
        if not score_path.exists():
            raise ServiceError(ERROR_INVALID_PARAMS, f"score not found: {score_path}")
        score_dict = load_json(score_path)
        return Score.from_dict(score_dict)

    def _resolve_local_path(self, raw_path: str) -> Path:
        path = Path(raw_path)
        if not path.is_absolute():
            path = self.root_dir / path
        resolved = path.resolve()

        try:
            resolved.relative_to(self.root_dir)
        except ValueError as exc:
            raise ServiceError(ERROR_INVALID_PARAMS, f"path out of workspace: {raw_path}") from exc

        return resolved

    def _log_task(self, task_id: str, text: str) -> None:
        log_line(self.root_dir / "logs" / "tasks" / f"{task_id}.log", text)

    def _log_render(self, task_id: str, text: str) -> None:
        log_line(self.root_dir / "logs" / "render" / f"{task_id}.log", text)

    def _log_export(self, task_id: str, text: str) -> None:
        log_line(self.root_dir / "logs" / "export" / f"{task_id}.log", text)


def handle_call(operation: Callable[[dict[str, Any]], dict[str, Any]], payload: dict[str, Any]) -> dict[str, Any]:
    try:
        data = operation(payload)
        return {
            "code": 0,
            "message": "ok",
            "data": data,
        }
    except ServiceError as exc:
        return {
            "code": exc.code,
            "message": exc.message,
            "data": {},
        }
    except Exception as exc:
        return {
            "code": ERROR_INVALID_PARAMS,
            "message": str(exc),
            "data": {"traceback": traceback.format_exc(limit=3)},
        }


def build_manifest_index(root_dir: Path) -> None:
    root_dir = root_dir.resolve()
    projects_dir = root_dir / "projects"
    output = {"projects": []}
    if projects_dir.exists():
        for project_dir in sorted(p for p in projects_dir.iterdir() if p.is_dir()):
            project_meta_path = project_dir / "project.json"
            if not project_meta_path.exists():
                continue
            project_meta = load_json(project_meta_path)
            output["projects"].append(project_meta)
    dump_json(root_dir / "projects" / "index.json", output)
