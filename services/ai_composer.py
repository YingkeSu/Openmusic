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
from .utils import beats_to_duration, clamp, midi_to_pitch, parse_duration_to_beats, parse_pitch, pitch_to_midi


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

        system_prompt = self._build_system_prompt()
        user_prompt = self._build_user_prompt(
            intent=intent,
            bars=bars,
            beats_per_bar=beats_per_bar,
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
            "- pitch range target: D3 to A5 (playable piano melody)\n"
            "- support variable rhythm using durations: 1/8, 1/4, 1/2, 3/4, 1/1\n"
            "- allow rests where phrasing needs breathing points\n"
            "- allow dyads/triads for texture, but keep melody clear\n"
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
            "    {\"bar\": 1, \"beat\": 1.0, \"dur\": \"1/4\", \"pitches\": [\"D4\"], \"vel\": 72, \"staff\": 1, \"voice\": 1},\n"
            "    {\"bar\": 1, \"beat\": 3.0, \"dur\": \"1/2\", \"is_rest\": true, \"staff\": 1, \"voice\": 1},\n"
            "    {\"bar\": 1, \"beat\": 1.0, \"dur\": \"1/2\", \"pitches\": [\"D3\",\"A3\"], \"vel\": 62, \"staff\": 2, \"voice\": 1}\n"
            "  ]\n"
            "}\n"
            "Hard requirements:\n"
            "- each bar+staff+voice timeline must be rhythmically closed to 4 beats\n"
            "- beat starts in [1.0, 4.0], and (beat-1 + duration_beats) <= 4\n"
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

        root_pitch = KEY_ROOT.get(str(intent["key"]), "C4")
        default_midi = pitch_to_midi(root_pitch)
        raw_notes = plan.get("notes") if isinstance(plan.get("notes"), list) else []
        if not raw_notes and isinstance(plan.get("events"), list):
            raw_notes = plan.get("events")  # compatibility alias
        grouped: dict[tuple[int, int, int], list[dict[str, Any]]] = {}

        for raw in raw_notes:
            if not isinstance(raw, dict):
                continue
            bar = int(clamp(int(raw.get("bar", 1)), 1, bars))
            beat = float(clamp(float(raw.get("beat", 1.0)), 1.0, 4.0))
            dur_str = str(raw.get("dur", "1/4"))
            try:
                duration = float(clamp(parse_duration_to_beats(dur_str), 0.125, 4.0))
            except Exception:
                duration = 1.0

            start = beat - 1.0
            if start + duration > beats_per_bar:
                duration = max(0.125, beats_per_bar - start)

            staff = int(clamp(int(raw.get("staff", 1)), 1, 2))
            voice = int(clamp(int(raw.get("voice", 1)), 1, 2))
            is_rest = bool(raw.get("is_rest", False) or raw.get("rest", False))
            vel = int(clamp(int(raw.get("vel", 72)), 45, 110))

            pitch_list: list[str] = []
            if isinstance(raw.get("pitches"), list):
                pitch_list = [str(p).strip() for p in raw.get("pitches", []) if str(p).strip()]
            elif raw.get("pitch"):
                pitch_list = [str(raw.get("pitch")).strip()]

            normalized: list[str] = []
            for pitch in pitch_list:
                try:
                    midi_val = int(clamp(pitch_to_midi(pitch), 36, 90))
                    normalized.append(midi_to_pitch(midi_val))
                except Exception:
                    continue

            if not is_rest and not normalized:
                normalized = [midi_to_pitch(int(clamp(default_midi, 52, 84)))]

            grouped.setdefault((bar, staff, voice), []).append(
                {
                    "beat": beat,
                    "duration": duration,
                    "vel": vel,
                    "is_rest": is_rest,
                    "pitches": normalized,
                }
            )

        # Guarantee main melody voice exists.
        for bar in range(1, bars + 1):
            key = (bar, 1, 1)
            if key not in grouped or not grouped[key]:
                grouped[key] = [
                    {
                        "beat": 1.0,
                        "duration": 1.0,
                        "vel": 72,
                        "is_rest": False,
                        "pitches": [midi_to_pitch(int(clamp(default_midi, 52, 84)))],
                    },
                    {"beat": 2.0, "duration": 1.0, "vel": 72, "is_rest": True, "pitches": []},
                    {
                        "beat": 3.0,
                        "duration": 1.0,
                        "vel": 70,
                        "is_rest": False,
                        "pitches": [midi_to_pitch(int(clamp(default_midi + 2, 52, 86)))],
                    },
                    {"beat": 4.0, "duration": 1.0, "vel": 68, "is_rest": True, "pitches": []},
                ]

        # Generate left hand accompaniment if absent.
        has_left = any(staff == 2 for (_, staff, _), items in grouped.items() if items)
        if not has_left:
            for bar in range(1, bars + 1):
                bass = int(clamp(default_midi - 24 + ((bar + 1) % 2) * 2, 33, 57))
                grouped[(bar, 2, 1)] = [
                    {
                        "beat": 1.0,
                        "duration": 2.0,
                        "vel": 62,
                        "is_rest": False,
                        "pitches": [midi_to_pitch(bass), midi_to_pitch(int(clamp(bass + 7, 36, 64)))],
                    },
                    {
                        "beat": 3.0,
                        "duration": 2.0,
                        "vel": 60,
                        "is_rest": False,
                        "pitches": [midi_to_pitch(int(clamp(bass - 2, 33, 55))), midi_to_pitch(int(clamp(bass + 5, 36, 64)))],
                    },
                ]

        # Normalize each voice timeline with rests and non-overlap.
        normalized_events: list[dict[str, Any]] = []
        for (bar, staff, voice), items in grouped.items():
            items.sort(key=lambda x: (float(x["beat"]), float(x["duration"])))
            cursor = 0.0
            for item in items:
                start = max(cursor, float(item["beat"]) - 1.0)
                if start > beats_per_bar - 1e-6:
                    continue
                if start > cursor + 1e-6:
                    normalized_events.append(
                        {
                            "bar": bar,
                            "beat": cursor + 1.0,
                            "duration": start - cursor,
                            "is_rest": True,
                            "pitches": [],
                            "vel": 64,
                            "staff": staff,
                            "voice": voice,
                        }
                    )
                dur = float(item["duration"])
                dur = max(0.125, min(dur, beats_per_bar - start))
                normalized_events.append(
                    {
                        "bar": bar,
                        "beat": start + 1.0,
                        "duration": dur,
                        "is_rest": bool(item["is_rest"]),
                        "pitches": list(item["pitches"]),
                        "vel": int(item["vel"]),
                        "staff": staff,
                        "voice": voice,
                    }
                )
                cursor = max(cursor, start + dur)
            if cursor < beats_per_bar - 1e-6:
                normalized_events.append(
                    {
                        "bar": bar,
                        "beat": cursor + 1.0,
                        "duration": beats_per_bar - cursor,
                        "is_rest": True,
                        "pitches": [],
                        "vel": 64,
                        "staff": staff,
                        "voice": voice,
                    }
                )

        normalized_events.sort(key=lambda x: (x["bar"], x["staff"], x["voice"], x["beat"]))

        notes: list[ScoreNote] = []
        for idx, event in enumerate(normalized_events, start=1):
            pitch_list = event["pitches"] if not event["is_rest"] else []
            note = ScoreNote(
                note_id=f"n_{idx:06d}",
                bar=int(event["bar"]),
                beat=round(float(event["beat"]), 3),
                dur=beats_to_duration(float(event["duration"])),
                pitch=pitch_list[0] if pitch_list else "",
                pitches=pitch_list,
                is_rest=bool(event["is_rest"]),
                staff=int(event["staff"]),
                voice=int(event["voice"]),
                vel=int(event["vel"]),
            )
            notes.append(note)

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
