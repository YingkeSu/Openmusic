from __future__ import annotations

import json
import math
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from .models import Score
from .utils import parse_duration_to_beats, pitch_to_midi, time_signature_parts


@dataclass
class VideoRenderResult:
    mp4_path: Path
    sync_delta_ms: int
    mode: str


@dataclass
class VideoRenderer:
    fps: int = 12
    width: int = 960
    height: int = 540

    def render(
        self,
        score: Score,
        wav_path: Path,
        mp4_path: Path,
        played_color: str = "#000000",
        unplayed_color: str = "#C8C8C8",
    ) -> VideoRenderResult:
        if not wav_path.exists():
            raise FileNotFoundError(f"wav not found: {wav_path}")

        ffmpeg_bin = shutil.which("ffmpeg")
        if ffmpeg_bin:
            return self._render_with_ffmpeg(
                ffmpeg_bin,
                score,
                wav_path,
                mp4_path,
                played_color,
                unplayed_color,
            )

        # Fallback placeholder when ffmpeg is unavailable.
        mp4_path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "format": "placeholder_mp4",
            "reason": "ffmpeg_not_found",
            "note": "Install ffmpeg to produce a playable MP4.",
            "tempo_bpm": score.meta.tempo_bpm,
            "bars": score.meta.bars,
            "fps": self.fps,
        }
        mp4_path.write_bytes(json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8"))
        return VideoRenderResult(mp4_path=mp4_path, sync_delta_ms=0, mode="placeholder")

    def _render_with_ffmpeg(
        self,
        ffmpeg_bin: str,
        score: Score,
        wav_path: Path,
        mp4_path: Path,
        played_color: str,
        unplayed_color: str,
    ) -> VideoRenderResult:
        mp4_path.parent.mkdir(parents=True, exist_ok=True)

        beats_per_bar, _ = time_signature_parts(score.meta.time_signature)
        beat_sec = 60.0 / score.meta.tempo_bpm
        total_seconds = score.meta.bars * beats_per_bar * beat_sec
        total_frames = max(1, int(math.ceil(total_seconds * self.fps)))

        played_rgb = self._hex_to_rgb(played_color)
        unplayed_rgb = self._hex_to_rgb(unplayed_color)

        notes = sorted(score.notes, key=lambda n: (n.bar, n.beat, n.note_id))
        note_count = max(1, len(notes))
        x_step = max(1, (self.width - 120) // note_count)

        note_events = []
        for idx, note in enumerate(notes):
            start_beats = (note.bar - 1) * beats_per_bar + (note.beat - 1.0)
            duration_beats = parse_duration_to_beats(note.dur)
            start_sec = start_beats * beat_sec
            end_sec = (start_beats + duration_beats) * beat_sec
            midi = pitch_to_midi(note.pitch)
            y = self._pitch_to_y(midi)
            x = 60 + idx * x_step
            note_events.append((x, y, start_sec, end_sec))

        with tempfile.TemporaryDirectory(prefix="piano_frames_") as tmp:
            tmp_dir = Path(tmp)
            for frame_idx in range(total_frames):
                current_t = frame_idx / self.fps
                canvas = np.full((self.height, self.width, 3), 245, dtype=np.uint8)
                self._draw_staff(canvas)

                for x, y, _, end_sec in note_events:
                    color = played_rgb if current_t >= end_sec else unplayed_rgb
                    self._draw_rect(canvas, x, y, 18, 12, color)

                frame_path = tmp_dir / f"frame_{frame_idx:05d}.ppm"
                self._write_ppm(frame_path, canvas)

            cmd = [
                ffmpeg_bin,
                "-y",
                "-loglevel",
                "error",
                "-framerate",
                str(self.fps),
                "-i",
                str(tmp_dir / "frame_%05d.ppm"),
                "-i",
                str(wav_path),
                "-c:v",
                "libx264",
                "-pix_fmt",
                "yuv420p",
                "-c:a",
                "aac",
                "-shortest",
                str(mp4_path),
            ]
            completed = subprocess.run(cmd, capture_output=True, text=True, check=False)
            if completed.returncode != 0:
                raise RuntimeError(
                    f"ffmpeg failed ({completed.returncode}): {completed.stderr.strip()}"
                )

        return VideoRenderResult(mp4_path=mp4_path, sync_delta_ms=0, mode="ffmpeg")

    def _draw_staff(self, canvas: np.ndarray) -> None:
        y_start = self.height // 3
        spacing = 14
        for idx in range(5):
            y = y_start + idx * spacing
            canvas[y : y + 2, 40 : self.width - 40] = (180, 180, 180)

    def _draw_rect(
        self,
        canvas: np.ndarray,
        x: int,
        y: int,
        width: int,
        height: int,
        color: tuple[int, int, int],
    ) -> None:
        x0 = max(0, x)
        x1 = min(canvas.shape[1], x + width)
        y0 = max(0, y)
        y1 = min(canvas.shape[0], y + height)
        canvas[y0:y1, x0:x1] = color

    def _pitch_to_y(self, midi: int) -> int:
        clamped = max(48, min(84, midi))
        ratio = (clamped - 48) / (84 - 48)
        return int(self.height * 0.72 - ratio * self.height * 0.4)

    def _hex_to_rgb(self, color: str) -> tuple[int, int, int]:
        c = color.lstrip("#")
        if len(c) != 6:
            return (0, 0, 0)
        return (int(c[0:2], 16), int(c[2:4], 16), int(c[4:6], 16))

    def _write_ppm(self, path: Path, canvas: np.ndarray) -> None:
        header = f"P6\n{canvas.shape[1]} {canvas.shape[0]}\n255\n".encode("ascii")
        with path.open("wb") as f:
            f.write(header)
            f.write(canvas.tobytes())
