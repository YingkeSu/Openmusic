from __future__ import annotations

import json
import math
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any

from .ai_config import LLMRuntimeConfig
from .composer import KEY_ROOT
from .errors import ServiceError
from .models import Score, ScoreMeta, ScoreNote
from .utils import clamp, midi_to_pitch, parse_pitch, pitch_to_midi


@dataclass
class AIComposer:
    temperature: float = 0.7

    def compose(self, intent: dict[str, Any], runtime: LLMRuntimeConfig) -> Score:
        if not runtime.enabled:
            raise ServiceError(2001, "AI compose is not enabled: missing API key/base_url/model")

        plan = self._generate_plan(intent, runtime)
        return self._plan_to_score(intent, plan)

    def _generate_plan(self, intent: dict[str, Any], runtime: LLMRuntimeConfig) -> dict[str, Any]:
        tempo = int(intent["tempo_bpm"])
        duration_sec = int(intent["duration_sec"])
        beats_per_bar = 4
        total_beats = max(4, int(round(tempo * duration_sec / 60.0)))
        bars = math.ceil(total_beats / beats_per_bar)

        payload = {
            "model": runtime.model,
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "You are a piano melody arranger. Output strict JSON only, without markdown. "
                        "The JSON must include keys: meta, notes. "
                        "notes must be a list of exactly one quarter-note per beat."
                    ),
                },
                {
                    "role": "user",
                    "content": (
                        "Generate a structured melody for solo piano with the constraints below.\\n"
                        f"title: {intent['title']}\\n"
                        f"style: {intent['style']}\\n"
                        f"mood: {intent['mood']}\\n"
                        f"tempo_bpm: {tempo}\\n"
                        f"key: {intent['key']}\\n"
                        f"difficulty: {intent['difficulty']}\\n"
                        f"reference: {intent['reference']}\\n"
                        f"time_signature: 4/4\\n"
                        f"bars: {bars}\\n"
                        "Output schema example: {\"meta\": {\"time_signature\": \"4/4\", \"bars\": 8}, "
                        "\"notes\": [{\"bar\":1,\"beat\":1.0,\"pitch\":\"D4\",\"dur\":\"1/4\",\"vel\":72}]}."
                    ),
                },
            ],
            "temperature": self.temperature,
            "response_format": {"type": "json_object"},
            "stream": False,
        }

        response = self._post_chat_completion(runtime, payload)
        content = (
            response.get("choices", [{}])[0]
            .get("message", {})
            .get("content", "")
        )
        if not content.strip():
            raise ServiceError(2001, "empty AI response")

        try:
            payload = json.loads(content)
        except json.JSONDecodeError as exc:
            raise ServiceError(2001, f"invalid JSON from AI: {exc}") from exc

        if not isinstance(payload, dict):
            raise ServiceError(2001, "AI response JSON must be an object")
        return payload

    def _post_chat_completion(self, runtime: LLMRuntimeConfig, payload: dict[str, Any]) -> dict[str, Any]:
        url = runtime.base_url.rstrip("/") + "/chat/completions"
        req = urllib.request.Request(
            url=url,
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {runtime.api_key}",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=120) as resp:
                raw = resp.read().decode("utf-8")
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            raise ServiceError(
                2001,
                f"AI HTTP error {exc.code}: {body[:500]}",
            ) from exc
        except urllib.error.URLError as exc:
            raise ServiceError(2001, f"AI request failed: {exc.reason}") from exc

        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ServiceError(2001, f"AI response is not valid JSON: {exc}") from exc

        if not isinstance(parsed, dict):
            raise ServiceError(2001, "AI response root must be JSON object")
        return parsed

    def _plan_to_score(self, intent: dict[str, Any], plan: dict[str, Any]) -> Score:
        tempo = int(intent["tempo_bpm"])
        duration_sec = int(intent["duration_sec"])
        beats_per_bar = 4
        total_beats = max(4, int(round(tempo * duration_sec / 60.0)))
        bars = math.ceil(total_beats / beats_per_bar)

        raw_meta = plan.get("meta") if isinstance(plan.get("meta"), dict) else {}
        out_bars = int(raw_meta.get("bars", bars))
        if out_bars <= 0:
            out_bars = bars
        bars = min(max(1, out_bars), bars)

        grid_total_beats = bars * beats_per_bar
        root_pitch = KEY_ROOT.get(str(intent["key"]), "C4")
        default_midi = pitch_to_midi(root_pitch)

        pitches: list[int] = [default_midi for _ in range(grid_total_beats)]
        velocities: list[int] = [72 for _ in range(grid_total_beats)]

        raw_notes = plan.get("notes") if isinstance(plan.get("notes"), list) else []
        for raw in raw_notes:
            if not isinstance(raw, dict):
                continue
            try:
                bar = int(raw.get("bar", 1))
                beat = float(raw.get("beat", 1.0))
                pitch = str(raw.get("pitch", root_pitch))
                vel = int(raw.get("vel", 72))
                parse_pitch(pitch)
            except Exception:
                continue

            bar = int(clamp(bar, 1, bars))
            beat_slot = int(round(beat - 1.0))
            beat_slot = int(clamp(beat_slot, 0, beats_per_bar - 1))
            idx = (bar - 1) * beats_per_bar + beat_slot
            midi_val = int(clamp(pitch_to_midi(pitch), 48, 84))
            pitches[idx] = midi_val
            velocities[idx] = int(clamp(vel, 45, 110))

        # Carry-forward smoothing to avoid large gaps when sparse notes are returned.
        for i in range(1, len(pitches)):
            if pitches[i] == default_midi and pitches[i - 1] != default_midi:
                pitches[i] = pitches[i - 1]

        notes: list[ScoreNote] = []
        for i in range(grid_total_beats):
            bar = i // beats_per_bar + 1
            beat = float(i % beats_per_bar + 1)
            notes.append(
                ScoreNote(
                    note_id=f"n_{i + 1:06d}",
                    bar=bar,
                    beat=beat,
                    pitch=midi_to_pitch(pitches[i]),
                    dur="1/4",
                    vel=velocities[i],
                )
            )

        meta = ScoreMeta(
            time_signature="4/4",
            tempo_bpm=tempo,
            key=str(intent["key"]),
            duration_sec=duration_sec,
            style=str(intent["style"]),
            title=str(intent["title"]),
            mood=str(intent.get("mood", "calm")),
            difficulty=str(intent.get("difficulty", "medium")),
            reference=str(intent.get("reference", "")),
            bars=bars,
        )
        return Score(meta=meta, notes=notes)
