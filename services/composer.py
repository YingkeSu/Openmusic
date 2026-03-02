from __future__ import annotations

import math
from dataclasses import dataclass
from fractions import Fraction

from .models import Score, ScoreMeta, ScoreNote
from .styles import get_style_profile
from .utils import beats_to_duration, clamp, midi_to_pitch, parse_pitch, pitch_to_midi

KEY_ROOT = {
    "C": "C4",
    "C#": "C#4",
    "Db": "C#4",
    "D": "D4",
    "D#": "D#4",
    "Eb": "D#4",
    "E": "E4",
    "F": "F4",
    "F#": "F#4",
    "Gb": "F#4",
    "G": "G4",
    "G#": "G#4",
    "Ab": "G#4",
    "A": "A4",
    "A#": "A#4",
    "Bb": "A#4",
    "B": "B4",
}

RHYTHM_PATTERNS = {
    "easy": [
        [Fraction(1), Fraction(1), Fraction(1), Fraction(1)],
        [Fraction(2), Fraction(2)],
        [Fraction(1), Fraction(1), Fraction(2)],
    ],
    "medium": [
        [Fraction(1), Fraction(1), Fraction(1), Fraction(1)],
        [Fraction(1), Fraction(1), Fraction(2)],
        [Fraction(3, 2), Fraction(1, 2), Fraction(1), Fraction(1)],
        [Fraction(1), Fraction(1, 2), Fraction(1, 2), Fraction(1), Fraction(1)],
    ],
    "hard": [
        [Fraction(1, 2), Fraction(1, 2), Fraction(1), Fraction(1), Fraction(1)],
        [Fraction(1), Fraction(1, 2), Fraction(1, 2), Fraction(1), Fraction(1)],
        [Fraction(3, 2), Fraction(1, 2), Fraction(1), Fraction(1)],
        [Fraction(1), Fraction(1), Fraction(1), Fraction(1)],
    ],
}


@dataclass
class Composer:
    def compose(self, intent: dict) -> Score:
        tempo = int(intent["tempo_bpm"])
        duration_sec = int(intent["duration_sec"])
        key = str(intent["key"])
        style = str(intent["style"])
        mood = str(intent.get("mood", "calm"))
        difficulty = str(intent.get("difficulty", "medium"))
        title = str(intent.get("title", "Untitled"))
        reference = str(intent.get("reference", ""))

        time_signature = "4/4"
        beats_per_bar = 4
        base_beats = max(4, int(round(tempo * duration_sec / 60.0)))
        bars = math.ceil(base_beats / beats_per_bar)

        style_profile = get_style_profile(style)
        pattern = style_profile.pitch_pattern
        root_pitch = KEY_ROOT.get(key, "C4")
        root_midi = pitch_to_midi(root_pitch)

        rhythm_bank = RHYTHM_PATTERNS.get(difficulty, RHYTHM_PATTERNS["medium"])

        notes: list[ScoreNote] = []
        note_counter = 1

        # Right hand melody (staff 1)
        melody_idx = 0
        for bar in range(1, bars + 1):
            rhythm = rhythm_bank[(bar - 1) % len(rhythm_bank)]
            beat_cursor = Fraction(1)

            for slot_idx, dur_beats in enumerate(rhythm):
                if beat_cursor > Fraction(5):
                    break
                if beat_cursor + dur_beats > Fraction(5):
                    dur_beats = Fraction(5) - beat_cursor
                if dur_beats <= 0:
                    continue

                global_slot = (bar - 1) * 8 + slot_idx
                pitch_offset = pattern[melody_idx % len(pattern)]
                melody_idx += 1

                octave_shift = 0
                if mood in {"sad", "dark"} and (global_slot % 8) > 4:
                    octave_shift = -12
                if mood in {"bright", "happy"} and (global_slot % 8) < 2:
                    octave_shift = 12

                midi_note = int(clamp(root_midi + pitch_offset + octave_shift, 50, 88))
                main_pitch = midi_to_pitch(midi_note)

                is_phrase_end = bar % 4 == 0 and beat_cursor >= Fraction(3)
                is_rest = is_phrase_end and slot_idx == len(rhythm) - 1 and dur_beats <= Fraction(1)

                pitches: list[str] = []
                if not is_rest:
                    if dur_beats >= Fraction(1) and (global_slot % 5 == 0):
                        third = int(clamp(midi_note + 4, 52, 90))
                        pitches = [main_pitch, midi_to_pitch(third)]
                    else:
                        pitches = [main_pitch]

                beat_float = float(beat_cursor)
                duration = beats_to_duration(float(dur_beats))
                note = ScoreNote(
                    note_id=f"n_{note_counter:06d}",
                    bar=bar,
                    beat=round(beat_float, 3),
                    dur=duration,
                    pitch=pitches[0] if pitches else "",
                    pitches=pitches,
                    is_rest=is_rest,
                    staff=1,
                    voice=1,
                    vel=70 + (global_slot % 18),
                )
                notes.append(note)
                note_counter += 1
                beat_cursor += dur_beats

        # Left hand accompaniment (staff 2)
        for bar in range(1, bars + 1):
            if difficulty == "hard":
                pattern_beats = [Fraction(1), Fraction(1), Fraction(1), Fraction(1)]
            else:
                pattern_beats = [Fraction(2), Fraction(2)]

            beat_cursor = Fraction(1)
            for idx, dur_beats in enumerate(pattern_beats):
                base = int(clamp(root_midi - 24 + ((bar + idx) % 2) * 2, 33, 57))
                chord = [midi_to_pitch(base), midi_to_pitch(int(clamp(base + 7, 36, 64)))]
                duration = beats_to_duration(float(dur_beats))
                note = ScoreNote(
                    note_id=f"n_{note_counter:06d}",
                    bar=bar,
                    beat=float(beat_cursor),
                    dur=duration,
                    pitch=chord[0],
                    pitches=chord,
                    is_rest=False,
                    staff=2,
                    voice=1,
                    vel=62 + (bar % 8),
                )
                notes.append(note)
                note_counter += 1
                beat_cursor += dur_beats

        # Ensure pitch strings are legal.
        for note in notes:
            for pitch in note.resolved_pitches():
                parse_pitch(pitch)

        meta = ScoreMeta(
            time_signature=time_signature,
            tempo_bpm=tempo,
            key=key,
            duration_sec=duration_sec,
            style=style,
            title=title,
            mood=mood,
            difficulty=difficulty,
            reference=reference,
            bars=bars,
        )
        return Score(meta=meta, notes=notes)
