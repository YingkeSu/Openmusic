from __future__ import annotations

import copy
import math
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
from .similarity import ScoreSimilarityEvaluator
from .storage import Storage
from .utils import (
    dump_json,
    load_json,
    log_line,
    parse_duration_to_beats,
    time_signature_parts,
    to_relpath,
    transpose_pitch,
    utc_now_iso,
)
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
        self.similarity_evaluator = ScoreSimilarityEvaluator()

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
        reference_score_path = self._resolve_reference_score_path(payload)
        if reference_score_path is None and self._is_senbonzakura_target(payload):
            raise ServiceError(
                ERROR_INVALID_PARAMS,
                "target_song=senbonzakura requires reference_score_path or assets/reference_scores/senbonzakura.score.json",
            )

        task = self.tasks.create(project_id, "", "compose")
        self.tasks.running(task.task_id)

        score: Score | None = None
        compose_error = ""
        compose_engine = "rule"
        reference_score_relpath = ""
        llm_debug: dict[str, Any] = {}
        llm_output_relpath = ""
        ai_runtime = resolve_llm_runtime(self.root_dir, payload, self.ai_registry)
        ai_requested = (
            reference_score_path is None
            and (compose_mode == "ai" or (compose_mode == "auto" and ai_runtime.enabled))
        )

        if reference_score_path is not None:
            score = self._load_reference_score(reference_score_path, intent)
            compose_engine = "reference"
            reference_score_relpath = to_relpath(reference_score_path, self.root_dir)
            self._log_task(task.task_id, f"use reference score: {reference_score_path}")
        else:
            for attempt in range(1, MAX_LLM_RETRY + 1):
                try:
                    if ai_requested:
                        compose_with_debug = getattr(self.ai_composer, "compose_with_debug", None)
                        if callable(compose_with_debug):
                            score, llm_debug = compose_with_debug(intent, ai_runtime)
                        else:
                            score = self.ai_composer.compose(intent, ai_runtime)
                            llm_debug = {}
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
            if compose_engine == "ai" and llm_debug:
                llm_output_path = self.storage.llm_output_path(project_id, version)
                dump_json(
                    llm_output_path,
                    {
                        "project_id": project_id,
                        "version": version,
                        "generated_at": utc_now_iso(),
                        "llm": llm_debug,
                    },
                )
                llm_output_relpath = to_relpath(llm_output_path, self.root_dir)

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
            "reference_score": reference_score_relpath,
            "llm_output": llm_output_relpath,
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
                base_pitch = (
                    str(notes[note_id].get("pitch", "")).strip()
                    or (notes[note_id].get("pitches") or ["D4"])[0]
                )
                notes[note_id]["pitch"] = transpose_pitch(base_pitch, semitones)
                notes[note_id]["pitches"] = [
                    transpose_pitch(pitch, semitones)
                    for pitch in notes[note_id].get("pitches", [])
                ] or [notes[note_id]["pitch"]]
                notes[note_id]["is_rest"] = False
            elif edit_type == "set_duration":
                dur = str(edit.get("dur", "")).strip()
                if not dur:
                    message = "dur is required for set_duration"
                    self.tasks.failed(task.task_id, message, base_version)
                    raise ServiceError(ERROR_INVALID_PARAMS, message)
                notes[note_id]["dur"] = dur
            elif edit_type == "toggle_rest":
                as_rest = bool(edit.get("is_rest", True))
                notes[note_id]["is_rest"] = as_rest
                if as_rest:
                    notes[note_id]["pitch"] = ""
                    notes[note_id]["pitches"] = []
                else:
                    fallback = str(edit.get("pitch", "")).strip() or "D4"
                    notes[note_id]["pitch"] = fallback
                    notes[note_id]["pitches"] = [fallback]
            elif edit_type == "set_pitches":
                raw = edit.get("pitches")
                if not isinstance(raw, list) or not raw:
                    message = "pitches must be non-empty list for set_pitches"
                    self.tasks.failed(task.task_id, message, base_version)
                    raise ServiceError(ERROR_INVALID_PARAMS, message)
                pitch_list = [str(p).strip() for p in raw if str(p).strip()]
                if not pitch_list:
                    message = "pitches must include valid values"
                    self.tasks.failed(task.task_id, message, base_version)
                    raise ServiceError(ERROR_INVALID_PARAMS, message)
                notes[note_id]["pitches"] = pitch_list
                notes[note_id]["pitch"] = pitch_list[0]
                notes[note_id]["is_rest"] = False
            else:
                message = f"unsupported edit type: {edit_type}"
                self.tasks.failed(task.task_id, message, base_version)
                raise ServiceError(ERROR_INVALID_PARAMS, message)

        try:
            self._normalize_score_timeline(updated_score)
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

    def evaluate_similarity(self, payload: dict[str, Any]) -> dict[str, Any]:
        self._require_fields(payload, ["project_id", "version"])
        project_id = str(payload["project_id"]).strip()
        version = str(payload["version"]).strip()
        threshold = float(payload.get("threshold", 95.0))
        if threshold < 0.0 or threshold > 100.0:
            raise ServiceError(ERROR_INVALID_PARAMS, "threshold must be in [0, 100]")

        reference_path = self._resolve_reference_score_path(payload)
        if reference_path is None:
            raise ServiceError(
                ERROR_INVALID_PARAMS,
                "reference_score_path is required (or set target_song to senbonzakura with local reference file)",
            )

        generated = self._load_score(project_id, version)
        reference = self._load_reference_score(reference_path, {})
        result = self.similarity_evaluator.evaluate(generated, reference, threshold=threshold)

        report_path = self.storage.similarity_report_path(project_id, version)
        dump_json(
            report_path,
            {
                "project_id": project_id,
                "version": version,
                "reference_score_path": str(reference_path),
                "evaluated_at": utc_now_iso(),
                "result": result,
            },
        )

        return {
            "project_id": project_id,
            "version": version,
            "reference_score_path": to_relpath(reference_path, self.root_dir),
            "report_path": to_relpath(report_path, self.root_dir),
            **result,
        }

    def get_task(self, task_id: str) -> dict[str, Any]:
        record = self.tasks.get(task_id)
        if record is None:
            raise ServiceError(ERROR_INVALID_PARAMS, f"task not found: {task_id}")
        return record.to_dict()

    def list_projects(self) -> dict[str, Any]:
        projects_dir = self.storage.projects_dir
        projects: list[dict[str, Any]] = []
        if projects_dir.exists():
            for project_dir in sorted((p for p in projects_dir.iterdir() if p.is_dir()), key=lambda p: p.name):
                project_id = project_dir.name
                project_meta = self.storage.load_project_meta(project_id) or {
                    "project_id": project_id,
                    "title": project_id,
                    "created_at": "",
                    "updated_at": "",
                    "active_version": "",
                }
                versions = self.storage.list_versions(project_id)
                projects.append(
                    {
                        "project_id": project_meta.get("project_id", project_id),
                        "title": project_meta.get("title", project_id),
                        "created_at": project_meta.get("created_at", ""),
                        "updated_at": project_meta.get("updated_at", ""),
                        "active_version": project_meta.get("active_version", ""),
                        "versions": versions,
                    }
                )
        projects.sort(key=lambda item: str(item.get("updated_at", "")), reverse=True)
        return {"projects": projects}

    def get_project(self, project_id: str) -> dict[str, Any]:
        project_id = project_id.strip()
        if not project_id:
            raise ServiceError(ERROR_INVALID_PARAMS, "project_id is required")
        project_meta = self.storage.load_project_meta(project_id)
        if project_meta is None:
            raise ServiceError(ERROR_INVALID_PARAMS, f"project not found: {project_id}")
        versions = self.storage.list_versions(project_id)
        return {
            "project": project_meta,
            "versions": versions,
        }

    def get_score(self, project_id: str, version: str) -> dict[str, Any]:
        project_id = project_id.strip()
        version = version.strip()
        if not project_id or not version:
            raise ServiceError(ERROR_INVALID_PARAMS, "project_id and version are required")
        score_path = self.storage.score_path(project_id, version)
        if not score_path.exists():
            raise ServiceError(ERROR_INVALID_PARAMS, f"score not found: {score_path}")
        score = load_json(score_path)
        return {
            "project_id": project_id,
            "version": version,
            "score": score,
            "score_path": to_relpath(score_path, self.root_dir),
        }

    def get_llm_output(self, project_id: str, version: str) -> dict[str, Any]:
        project_id = project_id.strip()
        version = version.strip()
        if not project_id or not version:
            raise ServiceError(ERROR_INVALID_PARAMS, "project_id and version are required")
        llm_path = self.storage.llm_output_path(project_id, version)
        if not llm_path.exists():
            raise ServiceError(ERROR_INVALID_PARAMS, f"llm output not found: {llm_path}")
        payload = load_json(llm_path)
        return {
            "project_id": project_id,
            "version": version,
            "llm_output": payload,
            "llm_output_path": to_relpath(llm_path, self.root_dir),
        }

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

    def _load_reference_score(self, path: Path, intent: dict[str, Any]) -> Score:
        if not path.exists():
            raise ServiceError(ERROR_INVALID_PARAMS, f"reference score not found: {path}")
        payload = load_json(path)
        score = Score.from_dict(payload)
        if intent:
            score.meta.title = str(intent.get("title", score.meta.title))
            score.meta.style = str(intent.get("style", score.meta.style))
            score.meta.mood = str(intent.get("mood", score.meta.mood))
            score.meta.difficulty = str(intent.get("difficulty", score.meta.difficulty))
            score.meta.reference = str(intent.get("reference", score.meta.reference))
            score.meta.key = str(intent.get("key", score.meta.key))
            score.meta.tempo_bpm = int(intent.get("tempo_bpm", score.meta.tempo_bpm))
            score.meta.duration_sec = int(intent.get("duration_sec", score.meta.duration_sec))
        return score

    def _resolve_reference_score_path(self, payload: dict[str, Any]) -> Path | None:
        explicit = str(payload.get("reference_score_path", "")).strip()
        if explicit:
            return self._resolve_local_path(explicit)

        if self._is_senbonzakura_target(payload):
            candidate = (self.root_dir / "assets" / "reference_scores" / "senbonzakura.score.json").resolve()
            if candidate.exists():
                return candidate
        return None

    def _is_senbonzakura_target(self, payload: dict[str, Any]) -> bool:
        target_song = str(payload.get("target_song", "")).strip().lower()
        if not target_song:
            target_song = str(payload.get("title", "")).strip().lower()
        normalized = target_song.replace("-", "").replace("_", "").replace(" ", "")
        return ("千本樱" in target_song) or ("senbonzakura" in normalized)

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

    def _normalize_score_timeline(self, score_dict: dict[str, Any]) -> None:
        meta = score_dict.setdefault("meta", {})
        time_signature = str(meta.get("time_signature", "4/4"))
        beats_per_bar, _ = time_signature_parts(time_signature)
        notes = score_dict.get("notes", [])
        if not isinstance(notes, list) or not notes:
            meta["bars"] = max(1, int(meta.get("bars", 1) or 1))
            return

        timeline_by_track: dict[tuple[int, int], list[tuple[float, str, dict[str, Any], float]]] = {}
        for note in notes:
            bar = int(note.get("bar", 1))
            beat = float(note.get("beat", 1.0))
            staff = int(note.get("staff", 1))
            voice = int(note.get("voice", 1))
            duration = parse_duration_to_beats(str(note.get("dur", "1/4")))
            abs_start = (bar - 1) * beats_per_bar + (beat - 1.0)
            timeline_by_track.setdefault((staff, voice), []).append(
                (abs_start, str(note.get("note_id", "")), note, duration)
            )

        max_end = 0.0
        for events in timeline_by_track.values():
            events.sort(key=lambda item: (item[0], item[1]))
            cursor = 0.0
            for original_start, _, note, duration in events:
                start = max(original_start, cursor)
                in_bar = start % beats_per_bar
                if in_bar + duration > beats_per_bar + 1e-6:
                    start = math.ceil(start / beats_per_bar) * beats_per_bar
                bar_index = int(start // beats_per_bar)
                beat_in_bar = (start - bar_index * beats_per_bar) + 1.0
                note["bar"] = bar_index + 1
                note["beat"] = round(beat_in_bar, 3)
                cursor = start + duration
            max_end = max(max_end, cursor)

        required_bars = max(1, int(math.ceil(max_end / beats_per_bar)))
        meta["bars"] = max(int(meta.get("bars", 1) or 1), required_bars)

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
