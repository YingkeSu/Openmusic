from __future__ import annotations

from pathlib import Path

from services.ai_config import LLMConfigRegistry, resolve_llm_runtime
from services.models import Score, ScoreMeta, ScoreNote
from services.orchestrator import Orchestrator, handle_call


def test_llm_runtime_reads_deepseek_from_dotenv(tmp_path: Path) -> None:
    (tmp_path / ".env").write_text("DEEPSEEK_API_KEY=test_key\n", encoding="utf-8")
    registry = LLMConfigRegistry.load(
        Path(__file__).resolve().parent.parent / "services" / "config" / "llm_providers.json"
    )

    runtime = resolve_llm_runtime(tmp_path, {}, registry)
    assert runtime.provider_id == "deepseek"
    assert runtime.base_url == "https://api.deepseek.com/v1"
    assert runtime.model == "deepseek-chat"
    assert runtime.api_key == "test_key"
    assert runtime.enabled is True


class FakeAIComposer:
    def compose(self, intent: dict, runtime) -> Score:  # noqa: ANN001
        return Score(
            meta=ScoreMeta(
                time_signature="4/4",
                tempo_bpm=int(intent["tempo_bpm"]),
                key=str(intent["key"]),
                duration_sec=int(intent["duration_sec"]),
                style=str(intent["style"]),
                title=str(intent["title"]),
                mood=str(intent["mood"]),
                difficulty=str(intent["difficulty"]),
                reference=str(intent["reference"]),
                bars=2,
            ),
            notes=[
                ScoreNote(note_id="n_000001", bar=1, beat=1.0, pitch="D4", dur="1/4", vel=72),
                ScoreNote(note_id="n_000002", bar=1, beat=2.0, pitch="E4", dur="1/4", vel=72),
                ScoreNote(note_id="n_000003", bar=1, beat=3.0, pitch="F#4", dur="1/4", vel=72),
                ScoreNote(note_id="n_000004", bar=1, beat=4.0, pitch="A4", dur="1/4", vel=72),
                ScoreNote(note_id="n_000005", bar=2, beat=1.0, pitch="A4", dur="1/4", vel=72),
                ScoreNote(note_id="n_000006", bar=2, beat=2.0, pitch="F#4", dur="1/4", vel=72),
                ScoreNote(note_id="n_000007", bar=2, beat=3.0, pitch="E4", dur="1/4", vel=72),
                ScoreNote(note_id="n_000008", bar=2, beat=4.0, pitch="D4", dur="1/4", vel=72),
            ],
        )


def test_orchestrator_compose_ai_mode(tmp_path: Path) -> None:
    (tmp_path / ".env").write_text("DEEPSEEK_API_KEY=test_key\n", encoding="utf-8")
    orchestrator = Orchestrator(root_dir=tmp_path)
    orchestrator.ai_composer = FakeAIComposer()

    payload = {
        "project_id": "ai_mode_project",
        "title": "AI 编曲测试",
        "style": "ancient_cn",
        "mood": "calm",
        "tempo_bpm": 88,
        "key": "D",
        "duration_sec": 8,
        "difficulty": "medium",
        "reference": "古风",
        "compose_mode": "ai",
        "ai_provider": "deepseek",
    }

    resp = handle_call(orchestrator.compose, payload)
    assert resp["code"] == 0
    data = resp["data"]
    assert data["compose_engine"] == "ai"
    assert data["ai_provider"] == "deepseek"
    assert data["version"] == "v001"

    score_path = tmp_path / data["score_json"]
    assert score_path.exists()
