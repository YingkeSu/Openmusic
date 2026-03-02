from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass
class ScoreNote:
    note_id: str
    bar: int
    beat: float
    dur: str
    pitch: str = ""
    pitches: list[str] = field(default_factory=list)
    is_rest: bool = False
    staff: int = 1
    voice: int = 1
    vel: int = 72
    tie: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def resolved_pitches(self) -> list[str]:
        if self.is_rest:
            return []
        if self.pitches:
            return [p for p in self.pitches if p]
        if self.pitch:
            return [self.pitch]
        return []


@dataclass
class ScoreMeta:
    time_signature: str
    tempo_bpm: int
    key: str
    duration_sec: int
    style: str
    title: str
    mood: str
    difficulty: str
    reference: str
    bars: int

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class Score:
    meta: ScoreMeta
    notes: list[ScoreNote] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "meta": self.meta.to_dict(),
            "notes": [note.to_dict() for note in self.notes],
        }

    @staticmethod
    def from_dict(data: dict[str, Any]) -> "Score":
        meta = ScoreMeta(**data["meta"])
        notes = [ScoreNote(**note) for note in data.get("notes", [])]
        return Score(meta=meta, notes=notes)


@dataclass
class TaskRecord:
    task_id: str
    project_id: str
    version: str
    stage: str
    status: str
    started_at: str
    ended_at: str = ""
    error: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
