from __future__ import annotations

import math
import struct
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from fractions import Fraction
from pathlib import Path

from .constants import ERROR_COMPILE_FAILED
from .errors import ServiceError
from .models import Score
from .utils import (
    note_type_from_beats,
    parse_duration_to_beats,
    parse_pitch,
    pitch_to_midi,
    time_signature_parts,
)

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
class Compiler:
    def validate_score(self, score: Score) -> None:
        beats_per_bar, _ = time_signature_parts(score.meta.time_signature)
        bars = score.meta.bars

        if bars <= 0:
            raise ServiceError(ERROR_COMPILE_FAILED, "bars must be positive")

        durations: dict[int, float] = {bar: 0.0 for bar in range(1, bars + 1)}

        for note in score.notes:
            if note.bar < 1 or note.bar > bars:
                raise ServiceError(ERROR_COMPILE_FAILED, f"bar out of range: {note.bar}")

            dur_beats = parse_duration_to_beats(note.dur)
            if dur_beats <= 0:
                raise ServiceError(ERROR_COMPILE_FAILED, f"invalid duration: {note.dur}")

            if note.beat < 1.0:
                raise ServiceError(ERROR_COMPILE_FAILED, f"invalid beat: {note.beat}")

            note_end = note.beat + dur_beats
            if note_end > beats_per_bar + 1.0 + 1e-6:
                raise ServiceError(ERROR_COMPILE_FAILED, f"note overflow in bar {note.bar}")

            midi = pitch_to_midi(note.pitch)
            if midi < 21 or midi > 108:
                raise ServiceError(ERROR_COMPILE_FAILED, f"pitch out of range: {note.pitch}")

            durations[note.bar] += dur_beats

        for bar, total in durations.items():
            if not math.isclose(total, beats_per_bar, rel_tol=0.0, abs_tol=1e-6):
                raise ServiceError(
                    ERROR_COMPILE_FAILED,
                    f"bar duration not closed at bar {bar}: {total} beats",
                )

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

        notes_by_bar: dict[int, list] = {bar: [] for bar in range(1, score.meta.bars + 1)}
        for note in sorted(score.notes, key=lambda n: (n.bar, n.beat, n.note_id)):
            notes_by_bar[note.bar].append(note)

        for bar in range(1, score.meta.bars + 1):
            measure = ET.SubElement(part, "measure", number=str(bar))

            if bar == 1:
                attrs = ET.SubElement(measure, "attributes")
                ET.SubElement(attrs, "divisions").text = str(divisions)

                key = ET.SubElement(attrs, "key")
                ET.SubElement(key, "fifths").text = str(KEY_TO_FIFTHS.get(score.meta.key, 0))

                time = ET.SubElement(attrs, "time")
                ET.SubElement(time, "beats").text = str(beats_per_bar)
                ET.SubElement(time, "beat-type").text = str(beat_type)

                clef = ET.SubElement(attrs, "clef")
                ET.SubElement(clef, "sign").text = "G"
                ET.SubElement(clef, "line").text = "2"

                direction = ET.SubElement(measure, "direction", placement="above")
                direction_type = ET.SubElement(direction, "direction-type")
                ET.SubElement(direction_type, "metronome")
                sound = ET.SubElement(direction, "sound")
                sound.set("tempo", str(score.meta.tempo_bpm))

            for note in notes_by_bar[bar]:
                note_el = ET.SubElement(measure, "note")
                pitch_el = ET.SubElement(note_el, "pitch")
                step, accidental, octave = parse_pitch(note.pitch)
                ET.SubElement(pitch_el, "step").text = step
                if accidental != 0:
                    ET.SubElement(pitch_el, "alter").text = str(accidental)
                ET.SubElement(pitch_el, "octave").text = str(octave)

                duration_beats = parse_duration_to_beats(note.dur)
                ET.SubElement(note_el, "duration").text = str(int(round(duration_beats * divisions)))
                ET.SubElement(note_el, "voice").text = "1"
                ET.SubElement(note_el, "type").text = note_type_from_beats(duration_beats)
                ET.SubElement(note_el, "staff").text = "1"
                ET.SubElement(note_el, "notations")

        tree = ET.ElementTree(score_partwise)
        tree.write(output_path, encoding="utf-8", xml_declaration=True)

    def _write_midi(self, score: Score, output_path: Path) -> None:
        output_path.parent.mkdir(parents=True, exist_ok=True)

        ppq = 480
        beats_per_bar, _ = time_signature_parts(score.meta.time_signature)

        events: list[tuple[int, int, int, int]] = []
        for note in sorted(score.notes, key=lambda n: (n.bar, n.beat, n.note_id)):
            start_beats = (note.bar - 1) * beats_per_bar + (note.beat - 1.0)
            duration_beats = parse_duration_to_beats(note.dur)
            start_tick = int(round(start_beats * ppq))
            end_tick = int(round((start_beats + duration_beats) * ppq))
            midi_note = pitch_to_midi(note.pitch)
            velocity = max(1, min(127, int(note.vel)))
            # event_type: 0 -> note_off, 1 -> note_on (off first on same tick)
            events.append((start_tick, 1, midi_note, velocity))
            events.append((end_tick, 0, midi_note, 0))

        events.sort(key=lambda item: (item[0], item[1]))

        track_data = bytearray()

        # Tempo meta event.
        tempo_mpqn = int(round(60_000_000 / score.meta.tempo_bpm))
        track_data.extend(self._vlq(0))
        track_data.extend(b"\xFF\x51\x03")
        track_data.extend(tempo_mpqn.to_bytes(3, "big"))

        # Time signature meta event.
        track_data.extend(self._vlq(0))
        numerator, denominator = time_signature_parts(score.meta.time_signature)
        denominator_pow = int(math.log2(denominator))
        track_data.extend(b"\xFF\x58\x04")
        track_data.extend(bytes([numerator, denominator_pow, 24, 8]))

        # Program change to Acoustic Grand Piano.
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
