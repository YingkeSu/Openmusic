from __future__ import annotations

from dataclasses import dataclass

from .models import Score
from .utils import parse_duration_to_beats, pitch_to_midi, time_signature_parts


@dataclass
class ScoreSimilarityEvaluator:
    steps_per_beat: int = 8

    def evaluate(
        self,
        generated: Score,
        reference: Score,
        threshold: float = 95.0,
    ) -> dict:
        reference_tracks = sorted({(note.staff, note.voice) for note in reference.notes})
        if not reference_tracks:
            reference_tracks = [(1, 1)]

        track_results: list[dict] = []
        weighted_total = 0.0
        weighted_score = 0.0

        for staff, voice in reference_tracks:
            ref_tokens = self._build_track_tokens(reference, staff, voice)
            gen_tokens = self._build_track_tokens(generated, staff, voice)

            ref_tokens = self._trim_trailing_rests(ref_tokens)
            gen_tokens = self._trim_trailing_rests(gen_tokens)

            span = max(1, len(ref_tokens), len(gen_tokens))
            ref_tokens += ["REST"] * (span - len(ref_tokens))
            gen_tokens += ["REST"] * (span - len(gen_tokens))

            matches = sum(1 for idx in range(span) if ref_tokens[idx] == gen_tokens[idx])
            ratio = matches / span
            similarity = round(ratio * 100.0, 3)
            weight = max(1, sum(1 for item in ref_tokens if item != "REST"))

            weighted_total += weight
            weighted_score += ratio * weight
            track_results.append(
                {
                    "staff": staff,
                    "voice": voice,
                    "similarity": similarity,
                    "match_steps": matches,
                    "total_steps": span,
                    "weight": weight,
                }
            )

        overall_ratio = (weighted_score / weighted_total) if weighted_total > 0 else 0.0
        overall_similarity = round(overall_ratio * 100.0, 3)
        return {
            "similarity": overall_similarity,
            "threshold": float(threshold),
            "pass": overall_similarity >= float(threshold),
            "tracks": track_results,
            "steps_per_beat": self.steps_per_beat,
        }

    def _build_track_tokens(self, score: Score, staff: int, voice: int) -> list[str]:
        beats_per_bar, _ = time_signature_parts(score.meta.time_signature)
        total_steps = max(1, int(round(score.meta.bars * beats_per_bar * self.steps_per_beat)))
        out = ["REST"] * total_steps

        track_notes = [
            note
            for note in sorted(score.notes, key=lambda x: (x.bar, x.beat, x.note_id))
            if note.staff == staff and note.voice == voice
        ]
        for note in track_notes:
            start_beats = (note.bar - 1) * beats_per_bar + (float(note.beat) - 1.0)
            duration_beats = parse_duration_to_beats(note.dur)
            start_step = int(round(start_beats * self.steps_per_beat))
            dur_step = max(1, int(round(duration_beats * self.steps_per_beat)))
            if start_step >= total_steps:
                continue
            end_step = min(total_steps, start_step + dur_step)

            if note.is_rest:
                token = "REST"
            else:
                pitches = sorted(note.resolved_pitches(), key=pitch_to_midi)
                token = "+".join(pitches) if pitches else "REST"
            for idx in range(start_step, end_step):
                out[idx] = token
        return out

    def _trim_trailing_rests(self, items: list[str]) -> list[str]:
        idx = len(items) - 1
        while idx >= 0 and items[idx] == "REST":
            idx -= 1
        return items[: idx + 1] if idx >= 0 else []
