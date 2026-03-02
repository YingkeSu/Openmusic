from __future__ import annotations

import math
import struct
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path

from .constants import ERROR_COMPILE_FAILED
from .errors import ServiceError
from .models import Score, ScoreNote
from .utils import note_type_from_beats, parse_duration_to_beats, parse_pitch, pitch_to_midi, time_signature_parts

KEY_TO_FIFTHS = {
    "C": 0,
    "G": 1,
    "D": 2,
    "A": 3,
    "E": 4,
    "B": 5,
    "F#": 6,
    "C#": 7,
    "F": -1,
    "Bb": -2,
    "Eb": -3,
    "Ab": -4,
    "Db": -5,
    "Gb": -6,
    "Cb": -7,
}


@dataclass
class _Event:
    note: ScoreNote
    start: float
    duration: float


@dataclass
class Compiler:
    def validate_score(self, score: Score) -> None:
        beats_per_bar, _ = time_signature_parts(score.meta.time_signature)
        bars = score.meta.bars

        if bars <= 0:
            raise ServiceError(ERROR_COMPILE_FAILED, "bars must be positive")

        grouped: dict[tuple[int, int, int], list[_Event]] = {}

        for note in score.notes:
            if note.bar < 1 or note.bar > bars:
                raise ServiceError(ERROR_COMPILE_FAILED, f"bar out of range: {note.bar}")

            if note.staff < 1 or note.staff > 2:
                raise ServiceError(ERROR_COMPILE_FAILED, f"unsupported staff index: {note.staff}")
            if note.voice < 1 or note.voice > 8:
                raise ServiceError(ERROR_COMPILE_FAILED, f"unsupported voice index: {note.voice}")

            dur_beats = parse_duration_to_beats(note.dur)
            if dur_beats <= 0:
                raise ServiceError(ERROR_COMPILE_FAILED, f"invalid duration: {note.dur}")

            start = float(note.beat) - 1.0
            if start < -1e-6:
                raise ServiceError(ERROR_COMPILE_FAILED, f"invalid beat: {note.beat}")

            note_end = start + dur_beats
            if note_end > beats_per_bar + 1e-6:
                raise ServiceError(ERROR_COMPILE_FAILED, f"note overflow in bar {note.bar}")

            pitches = note.resolved_pitches()
            if note.is_rest:
                if pitches:
                    raise ServiceError(ERROR_COMPILE_FAILED, "rest note cannot carry pitches")
            else:
                if not pitches:
                    raise ServiceError(ERROR_COMPILE_FAILED, f"note {note.note_id} has no pitch")
                for pitch in pitches:
                    parse_pitch(pitch)
                    midi = pitch_to_midi(pitch)
                    if midi < 21 or midi > 108:
                        raise ServiceError(ERROR_COMPILE_FAILED, f"pitch out of range: {pitch}")

            key = (note.bar, note.staff, note.voice)
            grouped.setdefault(key, []).append(_Event(note=note, start=start, duration=dur_beats))

        # Ensure no overlap inside same bar/staff/voice timeline.
        for key, events in grouped.items():
            events.sort(key=lambda e: (e.start, e.note.note_id))
            cursor = 0.0
            for event in events:
                if event.start < cursor - 1e-6:
                    raise ServiceError(
                        ERROR_COMPILE_FAILED,
                        f"overlap detected at bar/staff/voice={key}",
                    )
                cursor = max(cursor, event.start + event.duration)

    def compile(self, score: Score, musicxml_path: Path, midi_path: Path) -> None:
        self.validate_score(score)
        self._write_musicxml(score, musicxml_path)
        self._write_midi(score, midi_path)

    def _write_musicxml(self, score: Score, output_path: Path) -> None:
        output_path.parent.mkdir(parents=True, exist_ok=True)

        score_partwise = ET.Element("score-partwise", version="3.1")
        part_list = ET.SubElement(score_partwise, "part-list")
        score_part = ET.SubElement(part_list, "score-part", id="P1")
        ET.SubElement(score_part, "part-name").text = "Piano"

        part = ET.SubElement(score_partwise, "part", id="P1")
        beats_per_bar, beat_type = time_signature_parts(score.meta.time_signature)
        divisions = 480
        measure_ticks = int(beats_per_bar * divisions)

        notes_by_bar: dict[int, list[ScoreNote]] = {bar: [] for bar in range(1, score.meta.bars + 1)}
        for note in sorted(score.notes, key=lambda n: (n.bar, n.staff, n.voice, n.beat, n.note_id)):
            notes_by_bar[note.bar].append(note)

        for bar in range(1, score.meta.bars + 1):
            measure = ET.SubElement(part, "measure", number=str(bar))

            if bar == 1:
                attrs = ET.SubElement(measure, "attributes")
                ET.SubElement(attrs, "divisions").text = str(divisions)
                ET.SubElement(attrs, "staves").text = "2"

                key = ET.SubElement(attrs, "key")
                ET.SubElement(key, "fifths").text = str(KEY_TO_FIFTHS.get(score.meta.key, 0))

                time = ET.SubElement(attrs, "time")
                ET.SubElement(time, "beats").text = str(beats_per_bar)
                ET.SubElement(time, "beat-type").text = str(beat_type)

                clef1 = ET.SubElement(attrs, "clef", number="1")
                ET.SubElement(clef1, "sign").text = "G"
                ET.SubElement(clef1, "line").text = "2"
                clef2 = ET.SubElement(attrs, "clef", number="2")
                ET.SubElement(clef2, "sign").text = "F"
                ET.SubElement(clef2, "line").text = "4"

                direction = ET.SubElement(measure, "direction", placement="above")
                direction_type = ET.SubElement(direction, "direction-type")
                ET.SubElement(direction_type, "metronome")
                sound = ET.SubElement(direction, "sound")
                sound.set("tempo", str(score.meta.tempo_bpm))

            bar_notes = notes_by_bar[bar]
            for staff in (1, 2):
                staff_notes = [n for n in bar_notes if n.staff == staff]
                staff_notes.sort(key=lambda n: (n.voice, n.beat, n.note_id))

                voices = sorted({n.voice for n in staff_notes} or {1})
                for voice_idx, voice in enumerate(voices):
                    timeline = [n for n in staff_notes if n.voice == voice]
                    timeline.sort(key=lambda n: (n.beat, n.note_id))
                    cursor = 0.0

                    for note in timeline:
                        start = float(note.beat) - 1.0
                        if start > cursor + 1e-6:
                            self._write_rest_note(
                                measure=measure,
                                duration_beats=start - cursor,
                                divisions=divisions,
                                voice=f"{staff}{voice}",
                                staff=staff,
                            )
                            cursor = start

                        self._write_event_note(
                            measure=measure,
                            note=note,
                            divisions=divisions,
                            voice=f"{staff}{voice}",
                            staff=staff,
                        )
                        cursor = max(cursor, start + parse_duration_to_beats(note.dur))

                    if cursor < beats_per_bar - 1e-6:
                        self._write_rest_note(
                            measure=measure,
                            duration_beats=beats_per_bar - cursor,
                            divisions=divisions,
                            voice=f"{staff}{voice}",
                            staff=staff,
                        )

                    if voice_idx < len(voices) - 1:
                        backup = ET.SubElement(measure, "backup")
                        ET.SubElement(backup, "duration").text = str(measure_ticks)

                if staff == 1:
                    backup = ET.SubElement(measure, "backup")
                    ET.SubElement(backup, "duration").text = str(measure_ticks)

        tree = ET.ElementTree(score_partwise)
        tree.write(output_path, encoding="utf-8", xml_declaration=True)

    def _write_event_note(
        self,
        measure: ET.Element,
        note: ScoreNote,
        divisions: int,
        voice: str,
        staff: int,
    ) -> None:
        duration_beats = parse_duration_to_beats(note.dur)
        duration_ticks = int(round(duration_beats * divisions))

        if note.is_rest:
            self._write_rest_note(measure, duration_beats, divisions, voice, staff)
            return

        pitches = note.resolved_pitches()
        for idx, pitch in enumerate(pitches):
            note_el = ET.SubElement(measure, "note")
            if idx > 0:
                ET.SubElement(note_el, "chord")
            pitch_el = ET.SubElement(note_el, "pitch")
            step, accidental, octave = parse_pitch(pitch)
            ET.SubElement(pitch_el, "step").text = step
            if accidental != 0:
                ET.SubElement(pitch_el, "alter").text = str(accidental)
            ET.SubElement(pitch_el, "octave").text = str(octave)
            ET.SubElement(note_el, "duration").text = str(duration_ticks)
            ET.SubElement(note_el, "voice").text = voice
            ET.SubElement(note_el, "type").text = note_type_from_beats(duration_beats)
            ET.SubElement(note_el, "staff").text = str(staff)
            ET.SubElement(note_el, "notations")

    def _write_rest_note(
        self,
        measure: ET.Element,
        duration_beats: float,
        divisions: int,
        voice: str,
        staff: int,
    ) -> None:
        duration_ticks = int(round(duration_beats * divisions))
        note_el = ET.SubElement(measure, "note")
        ET.SubElement(note_el, "rest")
        ET.SubElement(note_el, "duration").text = str(duration_ticks)
        ET.SubElement(note_el, "voice").text = voice
        ET.SubElement(note_el, "type").text = note_type_from_beats(duration_beats)
        ET.SubElement(note_el, "staff").text = str(staff)

    def _write_midi(self, score: Score, output_path: Path) -> None:
        output_path.parent.mkdir(parents=True, exist_ok=True)

        ppq = 480
        beats_per_bar, _ = time_signature_parts(score.meta.time_signature)

        events: list[tuple[int, int, int, int]] = []
        for note in sorted(score.notes, key=lambda n: (n.bar, n.beat, n.note_id)):
            if note.is_rest:
                continue
            pitches = note.resolved_pitches()
            if not pitches:
                continue

            start_beats = (note.bar - 1) * beats_per_bar + (note.beat - 1.0)
            duration_beats = parse_duration_to_beats(note.dur)
            start_tick = int(round(start_beats * ppq))
            end_tick = int(round((start_beats + duration_beats) * ppq))
            velocity = max(1, min(127, int(note.vel)))

            for pitch in pitches:
                midi_note = pitch_to_midi(pitch)
                events.append((start_tick, 1, midi_note, velocity))
                events.append((end_tick, 0, midi_note, 0))

        events.sort(key=lambda item: (item[0], item[1]))

        track_data = bytearray()

        tempo_mpqn = int(round(60_000_000 / score.meta.tempo_bpm))
        track_data.extend(self._vlq(0))
        track_data.extend(b"\xFF\x51\x03")
        track_data.extend(tempo_mpqn.to_bytes(3, "big"))

        track_data.extend(self._vlq(0))
        numerator, denominator = time_signature_parts(score.meta.time_signature)
        denominator_pow = int(math.log2(denominator))
        track_data.extend(b"\xFF\x58\x04")
        track_data.extend(bytes([numerator, denominator_pow, 24, 8]))

        track_data.extend(self._vlq(0))
        track_data.extend(b"\xC0\x00")

        last_tick = 0
        for tick, event_type, midi_note, velocity in events:
            delta = tick - last_tick
            track_data.extend(self._vlq(delta))
            if event_type == 1:
                track_data.extend(bytes([0x90, midi_note, velocity]))
            else:
                track_data.extend(bytes([0x80, midi_note, 0]))
            last_tick = tick

        track_data.extend(self._vlq(0))
        track_data.extend(b"\xFF\x2F\x00")

        header = b"MThd" + struct.pack(">IHHH", 6, 0, 1, ppq)
        track = b"MTrk" + struct.pack(">I", len(track_data)) + bytes(track_data)
        output_path.write_bytes(header + track)

    def _vlq(self, value: int) -> bytes:
        if value == 0:
            return b"\x00"
        buffer = []
        while value > 0:
            buffer.append(value & 0x7F)
            value >>= 7
        out = bytearray()
        for i, item in enumerate(reversed(buffer)):
            if i < len(buffer) - 1:
                out.append(item | 0x80)
            else:
                out.append(item)
        return bytes(out)
