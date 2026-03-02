from __future__ import annotations

import shutil
from dataclasses import dataclass
from pathlib import Path

from .utils import dump_json, load_json, utc_now_iso


@dataclass
class Storage:
    root_dir: Path

    def __post_init__(self) -> None:
        self.projects_dir.mkdir(parents=True, exist_ok=True)

    @property
    def projects_dir(self) -> Path:
        return self.root_dir / "projects"

    @property
    def logs_dir(self) -> Path:
        return self.root_dir / "logs"

    def project_dir(self, project_id: str) -> Path:
        return self.projects_dir / project_id

    def project_meta_path(self, project_id: str) -> Path:
        return self.project_dir(project_id) / "project.json"

    def version_dir(self, project_id: str, version: str) -> Path:
        return self.project_dir(project_id) / version

    def version_meta_path(self, project_id: str, version: str) -> Path:
        return self.version_dir(project_id, version) / "version.json"

    def score_path(self, project_id: str, version: str) -> Path:
        return self.version_dir(project_id, version) / "score.json"

    def musicxml_path(self, project_id: str, version: str) -> Path:
        return self.version_dir(project_id, version) / "song.musicxml"

    def midi_path(self, project_id: str, version: str) -> Path:
        return self.version_dir(project_id, version) / "song.mid"

    def wav_path(self, project_id: str, version: str) -> Path:
        return self.version_dir(project_id, version) / "song.wav"

    def mp4_path(self, project_id: str, version: str) -> Path:
        return self.version_dir(project_id, version) / "song.mp4"

    def manifest_path(self, project_id: str, version: str) -> Path:
        return self.version_dir(project_id, version) / "manifest.json"

    def llm_output_path(self, project_id: str, version: str) -> Path:
        return self.version_dir(project_id, version) / "llm_output.json"

    def exports_dir(self, project_id: str, version: str) -> Path:
        return self.project_dir(project_id) / "exports" / version

    def load_project_meta(self, project_id: str) -> dict | None:
        path = self.project_meta_path(project_id)
        if not path.exists():
            return None
        return load_json(path)

    def save_project_meta(self, project_id: str, payload: dict) -> None:
        dump_json(self.project_meta_path(project_id), payload)

    def list_versions(self, project_id: str) -> list[str]:
        pdir = self.project_dir(project_id)
        if not pdir.exists():
            return []
        versions = []
        for item in pdir.iterdir():
            if item.is_dir() and item.name.startswith("v") and item.name[1:].isdigit():
                versions.append(item.name)
        return sorted(versions, key=lambda v: int(v[1:]))

    def next_version(self, project_id: str) -> str:
        versions = self.list_versions(project_id)
        if not versions:
            return "v001"
        idx = int(versions[-1][1:]) + 1
        return f"v{idx:03d}"

    def ensure_project(self, project_id: str, title: str) -> dict:
        project = self.load_project_meta(project_id)
        now = utc_now_iso()
        if project is None:
            project = {
                "project_id": project_id,
                "title": title,
                "created_at": now,
                "updated_at": now,
                "active_version": "",
            }
        else:
            if title:
                project["title"] = title
            project["updated_at"] = now
        self.save_project_meta(project_id, project)
        return project

    def create_version(
        self,
        project_id: str,
        reason: str,
        parent_version: str = "",
        title: str = "",
    ) -> str:
        project = self.ensure_project(project_id, title)
        version = self.next_version(project_id)
        version_dir = self.version_dir(project_id, version)
        version_dir.mkdir(parents=True, exist_ok=True)

        version_meta = {
            "project_id": project_id,
            "version": version,
            "parent_version": parent_version,
            "reason": reason,
            "created_at": utc_now_iso(),
        }
        dump_json(self.version_meta_path(project_id, version), version_meta)

        project["active_version"] = version
        project["updated_at"] = utc_now_iso()
        self.save_project_meta(project_id, project)
        return version

    def load_score(self, project_id: str, version: str) -> dict:
        return load_json(self.score_path(project_id, version))

    def save_score(self, project_id: str, version: str, payload: dict) -> None:
        dump_json(self.score_path(project_id, version), payload)

    def clone_version_score(self, project_id: str, src_version: str, dst_version: str) -> None:
        src = self.score_path(project_id, src_version)
        dst = self.score_path(project_id, dst_version)
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)

    def copy_if_exists(self, src: Path, dst: Path) -> None:
        if src.exists():
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)
