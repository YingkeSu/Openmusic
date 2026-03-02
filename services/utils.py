from __future__ import annotations

import hashlib
import json
import math
from datetime import datetime, timezone
from fractions import Fraction
from pathlib import Path

NOTE_BASE = {
    "C": 0,
    "D": 2,
    "E": 4,
    "F": 5,
    "G": 7,
    "A": 9,
    "B": 11,
}

SEMITONE_TO_STEP = {
    0: ("C", 0),
    1: ("C", 1),
    2: ("D", 0),
    3: ("D", 1),
    4: ("E", 0),
    5: ("F", 0),
    6: ("F", 1),
    7: ("G", 0),
    8: ("G", 1),
    9: ("A", 0),
    10: ("A", 1),
    11: ("B", 0),
}


class DurationParseError(ValueError):
    pass


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def sha256_of_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(65_536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def dump_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def to_relpath(path: Path, root: Path) -> str:
    try:
        return str(path.relative_to(root))
    except ValueError:
        return str(path)


def parse_duration_to_beats(dur: str) -> float:
    try:
        fraction = Fraction(dur)
    except Exception as exc:
        raise DurationParseError(f"invalid duration: {dur}") from exc
    quarter = Fraction(1, 4)
    beats = fraction / quarter
    return float(beats)


def beats_to_duration(beats: float) -> str:
    whole_note_fraction = Fraction(beats).limit_denominator(64) * Fraction(1, 4)
    return f"{whole_note_fraction.numerator}/{whole_note_fraction.denominator}"


def parse_pitch(pitch: str) -> tuple[str, int, int]:
    if len(pitch) < 2:
        raise ValueError(f"invalid pitch: {pitch}")
    step = pitch[0].upper()
    if step not in NOTE_BASE:
        raise ValueError(f"invalid pitch step: {pitch}")

    accidental = 0
    octave_start = 1
    if len(pitch) >= 3 and pitch[1] in ("#", "b"):
        accidental = 1 if pitch[1] == "#" else -1
        octave_start = 2

    octave = int(pitch[octave_start:])
    return step, accidental, octave


def pitch_to_midi(pitch: str) -> int:
    step, accidental, octave = parse_pitch(pitch)
    semitone = NOTE_BASE[step] + accidental
    return (octave + 1) * 12 + semitone


def midi_to_pitch(midi: int) -> str:
    octave = (midi // 12) - 1
    semitone = midi % 12
    step, alter = SEMITONE_TO_STEP[semitone]
    accidental = "#" if alter == 1 else ""
    return f"{step}{accidental}{octave}"


def transpose_pitch(pitch: str, semitones: int) -> str:
    midi = pitch_to_midi(pitch) + semitones
    midi = max(21, min(108, midi))
    return midi_to_pitch(midi)


def pitch_to_freq(pitch: str) -> float:
    midi = pitch_to_midi(pitch)
    return 440.0 * (2.0 ** ((midi - 69) / 12.0))


def time_signature_parts(ts: str) -> tuple[int, int]:
    beats, beat_type = ts.split("/")
    return int(beats), int(beat_type)


def clamp(value: float, lower: float, upper: float) -> float:
    return max(lower, min(upper, value))


def log_line(path: Path, line: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(f"{utc_now_iso()} {line}\n")


def note_type_from_beats(beats: float) -> str:
    if math.isclose(beats, 4.0):
        return "whole"
    if math.isclose(beats, 2.0):
        return "half"
    if math.isclose(beats, 1.0):
        return "quarter"
    if math.isclose(beats, 0.5):
        return "eighth"
    if math.isclose(beats, 0.25):
        return "16th"
    return "quarter"
