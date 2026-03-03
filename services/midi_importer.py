from __future__ import annotations

import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import mido

from .models import Score, ScoreMeta, ScoreNote
from .utils import beats_to_duration, clamp, midi_to_pitch


@dataclass
class _MergedEvent:
    start_beats: float
    duration_beats: float
    staff: int
    pitches: list[str]
    vel: int


@dataclass
class MidiImporter:
    quant_beats: float = 0.125

    def import_file(self, midi_path: Path, intent: dict[str, Any] | None = None) -> Score:
        intent = intent or {}
        midi = mido.MidiFile(str(midi_path))
        ticks_per_beat = max(1, int(midi.ticks_per_beat))

        tempo_us = 500000
        numerator = 4
        denominator = 4
        abs_tick = 0
        active: dict[tuple[int, int], list[tuple[int, int]]] = {}
        notes: list[tuple[int, int, int, int]] = []

        for msg in mido.merge_tracks(midi.tracks):
            abs_tick += int(msg.time)
            if msg.type == "set_tempo" and tempo_us == 500000:
                tempo_us = int(msg.tempo)
            elif msg.type == "time_signature" and numerator == 4 and denominator == 4:
                numerator = int(msg.numerator)
                denominator = int(msg.denominator)
            elif msg.type == "note_on" and int(msg.velocity) > 0:
                key = (int(msg.channel), int(msg.note))
                active.setdefault(key, []).append((abs_tick, int(msg.velocity)))
            elif msg.type in {"note_off", "note_on"}:
                if msg.type == "note_on" and int(msg.velocity) > 0:
                    continue
                key = (int(msg.channel), int(msg.note))
                opened = active.get(key, [])
                if not opened:
                    continue
                start_tick, vel = opened.pop(0)
                if not opened:
                    active.pop(key, None)
                if abs_tick <= start_tick:
                    continue
                notes.append((start_tick, abs_tick, int(msg.note), vel))

        bpm = int(round(60_000_000 / max(1, tempo_us)))
        beats_per_bar = self._beats_per_bar(numerator, denominator)

        grouped: dict[tuple[int, int, int], dict[str, Any]] = {}
        for start_tick, end_tick, midi_note, vel in notes:
            start_beats = self._q(start_tick / ticks_per_beat)
            duration_beats = self._q(max(self.quant_beats, (end_tick - start_tick) / ticks_per_beat))
            if duration_beats <= 0:
                continue

            staff = 2 if midi_note < 60 else 1
            key = (int(round(start_beats / self.quant_beats)), int(round(duration_beats / self.quant_beats)), staff)
            item = grouped.setdefault(
                key,
                {
                    "start_beats": start_beats,
                    "duration_beats": duration_beats,
                    "staff": staff,
                    "pitches": [],
                    "vel_sum": 0,
                    "vel_n": 0,
                },
            )
            item["pitches"].append(midi_to_pitch(midi_note))
            item["vel_sum"] += vel
            item["vel_n"] += 1

        merged_events: list[_MergedEvent] = []
        for item in grouped.values():
            pitches = sorted(set(item["pitches"]))
            merged_events.append(
                _MergedEvent(
                    start_beats=float(item["start_beats"]),
                    duration_beats=float(item["duration_beats"]),
                    staff=int(item["staff"]),
                    pitches=pitches,
                    vel=int(round(item["vel_sum"] / max(1, item["vel_n"]))),
                )
            )

        by_staff: dict[int, list[_MergedEvent]] = {1: [], 2: []}
        for event in merged_events:
            by_staff.setdefault(event.staff, []).append(event)
        for staff in by_staff:
            by_staff[staff].sort(key=lambda x: (x.start_beats, x.duration_beats, x.pitches))

        raw_notes: list[dict[str, Any]] = []
        for staff, events in by_staff.items():
            voice_ends: list[float] = []
            for event in events:
                voice_idx = self._assign_voice(event.start_beats, voice_ends)
                start = event.start_beats
                remain = event.duration_beats
                while remain > 1e-6:
                    bar_end = (math.floor(start / beats_per_bar) + 1) * beats_per_bar
                    segment = min(remain, bar_end - start)
                    if segment <= 1e-6:
                        break
                    raw_notes.append(
                        {
                            "start": start,
                            "dur": segment,
                            "staff": staff,
                            "voice": voice_idx + 1,
                            "pitches": event.pitches,
                            "vel": int(clamp(event.vel, 30, 120)),
                        }
                    )
                    start += segment
                    remain -= segment
                voice_ends[voice_idx] = max(voice_ends[voice_idx], event.start_beats + event.duration_beats)

        raw_notes.sort(key=lambda x: (x["start"], x["staff"], x["voice"]))
        max_end = 0.0
        score_notes: list[ScoreNote] = []
        for idx, note in enumerate(raw_notes, start=1):
            start_beats = float(note["start"])
            duration_beats = float(note["dur"])
            bar = int(start_beats // beats_per_bar) + 1
            beat = (start_beats - (bar - 1) * beats_per_bar) + 1.0
            max_end = max(max_end, start_beats + duration_beats)
            pitches = [p for p in note["pitches"] if p]
            score_notes.append(
                ScoreNote(
                    note_id=f"n_{idx:06d}",
                    bar=bar,
                    beat=round(beat, 3),
                    dur=beats_to_duration(duration_beats),
                    pitch=pitches[0] if pitches else "",
                    pitches=pitches,
                    is_rest=not bool(pitches),
                    staff=int(note["staff"]),
                    voice=int(note["voice"]),
                    vel=int(note["vel"]),
                )
            )

        bars = max(1, int(math.ceil(max_end / beats_per_bar)))
        duration_sec = int(round(max_end * 60.0 / max(1, bpm)))
        time_signature = f"{numerator}/{denominator}"
        meta = ScoreMeta(
            time_signature=time_signature,
            tempo_bpm=int(intent.get("tempo_bpm", bpm)),
            key=str(intent.get("key", "C")),
            duration_sec=max(1, int(intent.get("duration_sec", duration_sec))),
            style=str(intent.get("style", "custom")),
            title=str(intent.get("title", midi_path.stem)),
            mood=str(intent.get("mood", "dramatic")),
            difficulty=str(intent.get("difficulty", "hard")),
            reference=str(intent.get("reference", f"imported from {midi_path.name}")),
            bars=bars,
        )
        return Score(meta=meta, notes=score_notes)

    def _assign_voice(self, start_beats: float, voice_ends: list[float]) -> int:
        for idx, end_at in enumerate(voice_ends):
            if start_beats >= end_at - 1e-6:
                return idx
        voice_ends.append(0.0)
        return len(voice_ends) - 1

    def _q(self, value: float) -> float:
        return round(value / self.quant_beats) * self.quant_beats

    def _beats_per_bar(self, numerator: int, denominator: int) -> float:
        if denominator <= 0:
            return 4.0
        return float(numerator * (4.0 / denominator))
