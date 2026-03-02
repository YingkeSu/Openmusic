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
from .utils import parse_duration_to_beats, parse_pitch, pitch_to_midi, time_signature_parts


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
    left_margin: int = 70
    right_margin: int = 70
    staff_top: int = 180
    staff_line_gap: int = 14

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
        usable_width = max(1, self.width - self.left_margin - self.right_margin)

        note_events = []
        for note in notes:
            start_beats = (note.bar - 1) * beats_per_bar + (note.beat - 1.0)
            duration_beats = parse_duration_to_beats(note.dur)
            start_sec = start_beats * beat_sec
            end_sec = (start_beats + duration_beats) * beat_sec
            midi = pitch_to_midi(note.pitch)
            x = self.left_margin + int(
                ((start_beats + duration_beats * 0.5) / (score.meta.bars * beats_per_bar))
                * usable_width
            )
            y, step_offset = self._pitch_to_staff_y(note.pitch)
            note_events.append((x, y, step_offset, start_sec, end_sec, duration_beats, midi))

        with tempfile.TemporaryDirectory(prefix="piano_frames_") as tmp:
            tmp_dir = Path(tmp)
            for frame_idx in range(total_frames):
                current_t = frame_idx / self.fps
                canvas = np.full((self.height, self.width, 3), 245, dtype=np.uint8)
                self._draw_staff(canvas, score.meta.bars, beats_per_bar, usable_width)
                self._draw_playhead(canvas, current_t, total_seconds, usable_width)

                for x, y, step_offset, _, end_sec, duration_beats, _ in note_events:
                    color = played_rgb if current_t >= end_sec else unplayed_rgb
                    self._draw_note(canvas, x, y, step_offset, duration_beats, color)

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

    def _draw_staff(
        self,
        canvas: np.ndarray,
        bars: int,
        beats_per_bar: int,
        usable_width: int,
    ) -> None:
        for idx in range(5):
            y = self.staff_top + idx * self.staff_line_gap
            self._draw_hline(
                canvas,
                y,
                self.left_margin - 8,
                self.width - self.right_margin + 8,
                (168, 168, 168),
                thickness=2,
            )

        total_beats = bars * beats_per_bar
        for bar in range(0, bars + 1):
            x = self.left_margin + int((bar * beats_per_bar / total_beats) * usable_width)
            thickness = 2 if bar in (0, bars) else 1
            self._draw_vline(
                canvas,
                x,
                self.staff_top - 2,
                self.staff_top + self.staff_line_gap * 4 + 2,
                (176, 176, 176),
                thickness=thickness,
            )

    def _draw_playhead(
        self,
        canvas: np.ndarray,
        current_t: float,
        total_seconds: float,
        usable_width: int,
    ) -> None:
        if total_seconds <= 0:
            return
        ratio = max(0.0, min(1.0, current_t / total_seconds))
        x = self.left_margin + int(ratio * usable_width)
        self._draw_vline(
            canvas,
            x,
            self.staff_top - 16,
            self.staff_top + self.staff_line_gap * 4 + 48,
            (64, 64, 64),
            thickness=2,
        )

    def _draw_note(
        self,
        canvas: np.ndarray,
        x: int,
        y: int,
        step_offset: int,
        duration_beats: float,
        color: tuple[int, int, int],
    ) -> None:
        rx = 8
        ry = 6
        self._draw_filled_ellipse(canvas, x, y, rx, ry, color)

        # Draw a stem for notes shorter than whole note.
        if duration_beats < 4.0:
            stem_len = 30
            if step_offset <= 4:
                # Below/at middle line -> stem up.
                stem_x = x + rx - 1
                self._draw_vline(canvas, stem_x, y - stem_len, y, color, thickness=2)
            else:
                # Above middle line -> stem down.
                stem_x = x - rx + 1
                self._draw_vline(canvas, stem_x, y, y + stem_len, color, thickness=2)

        self._draw_ledger_lines(canvas, x, step_offset, color)

    def _pitch_to_staff_y(self, pitch: str) -> tuple[int, int]:
        # Treble staff bottom line is E4 -> step offset 0.
        note_step = self._diatonic_index(pitch)
        bottom_line_step = self._diatonic_index("E4")
        step_offset = note_step - bottom_line_step
        half_gap = self.staff_line_gap / 2.0
        y_bottom_line = self.staff_top + self.staff_line_gap * 4
        y = int(round(y_bottom_line - step_offset * half_gap))
        return y, step_offset

    def _diatonic_index(self, pitch: str) -> int:
        step, _, octave = parse_pitch(pitch)
        step_map = {"C": 0, "D": 1, "E": 2, "F": 3, "G": 4, "A": 5, "B": 6}
        return octave * 7 + step_map[step]

    def _draw_ledger_lines(
        self,
        canvas: np.ndarray,
        x: int,
        step_offset: int,
        color: tuple[int, int, int],
    ) -> None:
        # Staff covers step offsets [0..8], line positions are even offsets.
        if step_offset < 0:
            line_step = -2
            while line_step >= step_offset:
                y = self._staff_y_from_step(line_step)
                self._draw_hline(canvas, y, x - 11, x + 11, color, thickness=2)
                line_step -= 2
        elif step_offset > 8:
            line_step = 10
            while line_step <= step_offset:
                y = self._staff_y_from_step(line_step)
                self._draw_hline(canvas, y, x - 11, x + 11, color, thickness=2)
                line_step += 2

    def _staff_y_from_step(self, step_offset: int) -> int:
        half_gap = self.staff_line_gap / 2.0
        y_bottom_line = self.staff_top + self.staff_line_gap * 4
        return int(round(y_bottom_line - step_offset * half_gap))

    def _draw_hline(
        self,
        canvas: np.ndarray,
        y: int,
        x0: int,
        x1: int,
        color: tuple[int, int, int],
        thickness: int = 1,
    ) -> None:
        y0 = max(0, y - thickness // 2)
        y1 = min(canvas.shape[0], y0 + thickness)
        xs = max(0, min(x0, x1))
        xe = min(canvas.shape[1], max(x0, x1))
        if xs >= xe:
            return
        canvas[y0:y1, xs:xe] = color

    def _draw_vline(
        self,
        canvas: np.ndarray,
        x: int,
        y0: int,
        y1: int,
        color: tuple[int, int, int],
        thickness: int = 1,
    ) -> None:
        x0 = max(0, x - thickness // 2)
        x1 = min(canvas.shape[1], x0 + thickness)
        ys = max(0, min(y0, y1))
        ye = min(canvas.shape[0], max(y0, y1))
        if ys >= ye:
            return
        canvas[ys:ye, x0:x1] = color

    def _draw_filled_ellipse(
        self,
        canvas: np.ndarray,
        cx: int,
        cy: int,
        rx: int,
        ry: int,
        color: tuple[int, int, int],
    ) -> None:
        x0 = max(0, cx - rx)
        x1 = min(canvas.shape[1], cx + rx + 1)
        y0 = max(0, cy - ry)
        y1 = min(canvas.shape[0], cy + ry + 1)
        if x0 >= x1 or y0 >= y1:
            return
        yy, xx = np.ogrid[y0:y1, x0:x1]
        mask = (((xx - cx) / max(1, rx)) ** 2 + ((yy - cy) / max(1, ry)) ** 2) <= 1.0
        region = canvas[y0:y1, x0:x1]
        region[mask] = color

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
