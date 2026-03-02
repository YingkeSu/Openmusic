from __future__ import annotations

import shutil
from dataclasses import dataclass
from pathlib import Path

from .constants import ERROR_EXPORT_FAILED
from .errors import ServiceError
from .utils import dump_json, sha256_of_file, to_relpath


@dataclass
class Exporter:
    root_dir: Path

    def export(
        self,
        project_id: str,
        version: str,
        version_dir: Path,
        export_dir: Path,
        manifest_path: Path,
        targets: list[str],
    ) -> tuple[Path, Path]:
        allowed = {"musicxml": "song.musicxml", "midi": "song.mid", "mp4": "song.mp4"}
        unknown = [target for target in targets if target not in allowed]
        if unknown:
            raise ServiceError(ERROR_EXPORT_FAILED, f"unsupported export targets: {unknown}")

        export_dir.mkdir(parents=True, exist_ok=True)

        exports: dict[str, str] = {}
        checksums: dict[str, str] = {}
        for target in targets:
            filename = allowed[target]
            src = version_dir / filename
            if not src.exists():
                raise ServiceError(
                    ERROR_EXPORT_FAILED,
                    f"required artifact not found: {src}",
                )
            dst = export_dir / filename
            shutil.copy2(src, dst)
            exports[target] = to_relpath(dst, self.root_dir)
            checksums[target] = sha256_of_file(dst)

        manifest = {
            "project_id": project_id,
            "version": version,
            "exports": exports,
            "checksum": checksums,
        }
        dump_json(manifest_path, manifest)
        dump_json(export_dir / "manifest.json", manifest)
        return export_dir, manifest_path
