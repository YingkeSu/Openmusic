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
from .styles import get_style_profile
from .utils import clamp, midi_to_pitch, parse_pitch, pitch_to_midi


@dataclass
class AIComposer:
    temperature: float = 0.55

    def compose(self, intent: dict[str, Any], runtime: LLMRuntimeConfig) -> Score:
        score, _ = self.compose_with_debug(intent, runtime)
        return score

    def compose_with_debug(
        self, intent: dict[str, Any], runtime: LLMRuntimeConfig
    ) -> tuple[Score, dict[str, Any]]:
        if not runtime.enabled:
            raise ServiceError(2001, "AI compose is not enabled: missing API key/base_url/model")

        plan, debug = self._generate_plan(intent, runtime)
        return self._plan_to_score(intent, plan), debug

    def _generate_plan(
        self, intent: dict[str, Any], runtime: LLMRuntimeConfig
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        tempo = int(intent["tempo_bpm"])
        duration_sec = int(intent["duration_sec"])
        beats_per_bar = 4
        total_beats = max(4, int(round(tempo * duration_sec / 60.0)))
        bars = math.ceil(total_beats / beats_per_bar)
        expected_notes = bars * beats_per_bar

        system_prompt = self._build_system_prompt()
        user_prompt = self._build_user_prompt(
            intent=intent,
            bars=bars,
            beats_per_bar=beats_per_bar,
            expected_notes=expected_notes,
        )

        request_payload = {
            "model": runtime.model,
            "messages": [
                {
                    "role": "system",
                    "content": system_prompt,
                },
                {
                    "role": "user",
                    "content": user_prompt,
                },
            ],
            "temperature": self.temperature,
            "response_format": {"type": "json_object"},
            "stream": False,
        }

        response = self._post_chat_completion(runtime, request_payload)
        content = (
            response.get("choices", [{}])[0]
            .get("message", {})
            .get("content", "")
        )
        if not content.strip():
            raise ServiceError(2001, "empty AI response")

        try:
            plan = json.loads(content)
        except json.JSONDecodeError as exc:
            plan = self._extract_json_object(content)
            if plan is None:
                raise ServiceError(2001, f"invalid JSON from AI: {exc}") from exc

        if not isinstance(plan, dict):
            raise ServiceError(2001, "AI response JSON must be an object")

        debug = {
            "provider": runtime.provider_id,
            "model": runtime.model,
            "base_url": runtime.base_url,
            "request_payload": request_payload,
            "raw_response": response,
            "raw_content": content,
            "parsed_plan": plan,
        }
        return plan, debug

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

    def _build_system_prompt(self) -> str:
        return (
            "You are an expert piano arranger for sheet-music-first generation. "
            "Return strict JSON only (no markdown, no prose). "
            "You must respect rhythm closure and bar boundaries, and keep the melody singable/playable."
        )

    def _build_user_prompt(
        self,
        intent: dict[str, Any],
        bars: int,
        beats_per_bar: int,
        expected_notes: int,
    ) -> str:
        style_id = str(intent.get("style", "custom"))
        style_profile = get_style_profile(style_id)
        prompt_rules = ", ".join(style_profile.prompt_rules) or "none"
        harmony_rules = ", ".join(style_profile.harmony_rules) or "none"
        eval_rules = ", ".join(style_profile.evaluation_rules) or "none"

        return (
            "Generate melody plan JSON for a solo piano right-hand line with exact timing grid.\n"
            "Constraints:\n"
            f"- title: {intent['title']}\n"
            f"- style: {style_id}\n"
            f"- mood: {intent['mood']}\n"
            f"- tempo_bpm: {intent['tempo_bpm']}\n"
            f"- key: {intent['key']}\n"
            f"- difficulty: {intent['difficulty']}\n"
            f"- reference: {intent['reference']}\n"
            f"- time_signature: 4/4\n"
            f"- bars: {bars}\n"
            f"- beats_per_bar: {beats_per_bar}\n"
            f"- expected_note_count: {expected_notes}\n"
            "- pitch range target: D3 to A5 (playable piano melody)\n"
            "- avoid repeating the same pitch for more than 3 consecutive beats\n"
            "- prefer stepwise motion; allow occasional leaps for phrase peaks and cadences\n"
            "- keep phrase arcs: rise in first half, settle in second half\n"
            f"- style prompt rules: {prompt_rules}\n"
            f"- style harmony rules: {harmony_rules}\n"
            f"- style evaluation target: {eval_rules}\n"
            "Output schema:\n"
            "{\n"
            "  \"meta\": {\"time_signature\": \"4/4\", \"bars\": <int>, \"style_hint\": \"<string>\"},\n"
            "  \"notes\": [\n"
            "    {\"bar\": 1, \"beat\": 1.0, \"pitch\": \"D4\", \"dur\": \"1/4\", \"vel\": 72}\n"
            "  ]\n"
            "}\n"
            "Hard requirements:\n"
            "- notes must be an array with exactly expected_note_count entries\n"
            "- each bar must contain beats 1.0, 2.0, 3.0, 4.0 exactly once\n"
            "- dur must be \"1/4\" for every note\n"
            "- beat values must be one of [1.0, 2.0, 3.0, 4.0]\n"
            "- pitch must use scientific pitch notation like C4, F#4, Bb3\n"
        )

    def _extract_json_object(self, text: str) -> dict[str, Any] | None:
        start = text.find("{")
        end = text.rfind("}")
        if start == -1 or end == -1 or end <= start:
            return None
        segment = text[start : end + 1]
        try:
            parsed = json.loads(segment)
        except json.JSONDecodeError:
            return None
        if isinstance(parsed, dict):
            return parsed
        return None

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
