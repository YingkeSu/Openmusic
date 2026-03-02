from __future__ import annotations

import math
import wave
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from .constants import SAMPLE_RATE, WAV_CHANNELS, WAV_WIDTH_BYTES
from .models import Score
from .utils import parse_duration_to_beats, pitch_to_freq, time_signature_parts


@dataclass
class AudioRenderer:
    sample_rate: int = SAMPLE_RATE

    def render(self, score: Score, wav_path: Path, soundfont_path: Path) -> Path:
        if not soundfont_path.exists():
            raise FileNotFoundError(f"SoundFont not found: {soundfont_path}")

        wav_path.parent.mkdir(parents=True, exist_ok=True)

        beats_per_bar, _ = time_signature_parts(score.meta.time_signature)
        beat_sec = 60.0 / score.meta.tempo_bpm
        total_beats = score.meta.bars * beats_per_bar
        total_seconds = total_beats * beat_sec + 0.25

        samples = np.zeros(int(total_seconds * self.sample_rate), dtype=np.float32)

        for note in score.notes:
            start_beats = (note.bar - 1) * beats_per_bar + (note.beat - 1.0)
            duration_beats = parse_duration_to_beats(note.dur)

            start_idx = int(start_beats * beat_sec * self.sample_rate)
            duration_samples = max(1, int(duration_beats * beat_sec * self.sample_rate))
            end_idx = min(len(samples), start_idx + duration_samples)
            if start_idx >= len(samples):
                continue

            length = end_idx - start_idx
            if length <= 0:
                continue

            t = np.arange(length, dtype=np.float32) / self.sample_rate
            freq = pitch_to_freq(note.pitch)
            phase = 2.0 * math.pi * freq * t
            signal = np.sin(phase)

            velocity_amp = max(0.05, min(1.0, note.vel / 127.0))
            signal *= velocity_amp

            attack = min(length, int(0.01 * self.sample_rate))
            release = min(length, int(0.03 * self.sample_rate))
            if attack > 0:
                signal[:attack] *= np.linspace(0.0, 1.0, attack)
            if release > 0:
                signal[-release:] *= np.linspace(1.0, 0.0, release)

            samples[start_idx:end_idx] += signal

        peak = float(np.max(np.abs(samples))) if len(samples) else 1.0
        if peak > 0.99:
            samples /= peak

        pcm = (samples * 32767.0).astype(np.int16)
        stereo = np.column_stack((pcm, pcm)).ravel().tobytes()

        with wave.open(str(wav_path), "wb") as wav:
            wav.setnchannels(WAV_CHANNELS)
            wav.setsampwidth(WAV_WIDTH_BYTES)
            wav.setframerate(self.sample_rate)
            wav.writeframes(stereo)

        return wav_path
