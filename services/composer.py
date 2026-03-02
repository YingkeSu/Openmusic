from __future__ import annotations

import math
from dataclasses import dataclass

from .models import Score, ScoreMeta, ScoreNote
from .styles import get_style_profile
from .utils import clamp, midi_to_pitch, parse_pitch, pitch_to_midi

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
        total_beats = bars * beats_per_bar

        style_profile = get_style_profile(style)
        pattern = style_profile.pitch_pattern
        root_pitch = KEY_ROOT.get(key, "C4")
        root_midi = pitch_to_midi(root_pitch)

        density = {
            "easy": 1,
            "medium": 1,
            "hard": 2,
        }.get(difficulty, 1)

        notes: list[ScoreNote] = []
        note_counter = 1

        for beat_index in range(total_beats):
            bar = (beat_index // beats_per_bar) + 1
            beat_offset = beat_index % beats_per_bar

            subdivisions = density
            dur = "1/4" if subdivisions == 1 else "1/8"
            for sub in range(subdivisions):
                beat = 1.0 + beat_offset + (sub / subdivisions)
                pitch_offset = pattern[(beat_index + sub) % len(pattern)]
                octave_shift = 0
                if mood in {"sad", "dark"} and (beat_index % 8) > 4:
                    octave_shift = -12
                if mood in {"bright", "happy"} and (beat_index % 8) < 2:
                    octave_shift = 12
                midi_note = root_midi + pitch_offset + octave_shift
                midi_note = int(clamp(midi_note, 48, 84))
                pitch = midi_to_pitch(midi_note)

                notes.append(
                    ScoreNote(
                        note_id=f"n_{note_counter:06d}",
                        bar=bar,
                        beat=round(beat, 3),
                        pitch=pitch,
                        dur=dur,
                        vel=72 + ((beat_index + sub) % 10),
                    )
                )
                note_counter += 1

        # Ensure pitch strings are legal.
        for note in notes:
            parse_pitch(note.pitch)

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
