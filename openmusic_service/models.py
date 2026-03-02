from __future__ import annotations

from dataclasses import dataclass, asdict, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
import json
import uuid


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class Task:
    task_id: str
    project_id: str
    version: str
    stage: str
    status: str = "queued"
    started_at: str | None = None
    ended_at: str | None = None
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class Version:
    project_id: str
    version: str
    parent_version: str | None
    reason: str
    created_at: str = field(default_factory=now_iso)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class Project:
    project_id: str
    title: str
    created_at: str = field(default_factory=now_iso)
    updated_at: str = field(default_factory=now_iso)
    active_version: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class JsonStore:
    """Filesystem-backed storage for MVP metadata and artifacts."""

    def __init__(self, root: Path) -> None:
        self.root = root
        self.projects_file = root / "db" / "projects.json"
        self.tasks_file = root / "db" / "tasks.json"
        self.versions_file = root / "db" / "versions.json"
        self.root.mkdir(parents=True, exist_ok=True)
        self.projects_file.parent.mkdir(parents=True, exist_ok=True)
        for path in (self.projects_file, self.tasks_file, self.versions_file):
            if not path.exists():
                path.write_text("{}", encoding="utf-8")

    @staticmethod
    def _read_dict(path: Path) -> dict[str, Any]:
        return json.loads(path.read_text(encoding="utf-8"))

    @staticmethod
    def _write_dict(path: Path, data: dict[str, Any]) -> None:
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    def upsert_project(self, project: Project) -> None:
        db = self._read_dict(self.projects_file)
        db[project.project_id] = project.to_dict()
        self._write_dict(self.projects_file, db)

    def get_project(self, project_id: str) -> Project | None:
        db = self._read_dict(self.projects_file)
        if project_id not in db:
            return None
        return Project(**db[project_id])

    def upsert_version(self, version: Version) -> None:
        db = self._read_dict(self.versions_file)
        key = f"{version.project_id}:{version.version}"
        db[key] = version.to_dict()
        self._write_dict(self.versions_file, db)

    def create_task(self, project_id: str, version: str, stage: str) -> Task:
        task = Task(task_id=str(uuid.uuid4()), project_id=project_id, version=version, stage=stage)
        db = self._read_dict(self.tasks_file)
        db[task.task_id] = task.to_dict()
        self._write_dict(self.tasks_file, db)
        return task

    def update_task(self, task: Task) -> None:
        db = self._read_dict(self.tasks_file)
        db[task.task_id] = task.to_dict()
        self._write_dict(self.tasks_file, db)

    def get_task(self, task_id: str) -> Task | None:
        db = self._read_dict(self.tasks_file)
        if task_id not in db:
            return None
        return Task(**db[task_id])
