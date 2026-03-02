from __future__ import annotations

from pathlib import Path

from services.constants import ERROR_DURATION_EXCEEDED, ERROR_RENDER_AUDIO_FAILED
from services.orchestrator import Orchestrator, handle_call
from services.utils import dump_json, load_json


def make_intent(project_id: str, duration_sec: int = 8) -> dict:
    return {
        "project_id": project_id,
        "title": "江南夜雨",
        "style": "ancient_cn",
        "mood": "calm",
        "tempo_bpm": 88,
        "key": "D",
        "duration_sec": duration_sec,
        "difficulty": "medium",
        "reference": "古风、空灵、可演奏",
    }


def test_compose_success(tmp_path: Path) -> None:
    orchestrator = Orchestrator(root_dir=tmp_path)
    resp = handle_call(orchestrator.compose, make_intent("p_tc_f_001", duration_sec=8))

    assert resp["code"] == 0
    data = resp["data"]
    assert data["version"] == "v001"

    for key in ["score_json", "musicxml", "midi"]:
        assert (tmp_path / data[key]).exists()

    task = orchestrator.get_task(data["task_id"])
    assert task["status"] == "success"
    assert task["stage"] == "compose"


def test_duration_limit(tmp_path: Path) -> None:
    orchestrator = Orchestrator(root_dir=tmp_path)
    resp = handle_call(orchestrator.compose, make_intent("p_tc_f_002", duration_sec=61))

    assert resp["code"] == ERROR_DURATION_EXCEEDED


def test_audio_video_export_pipeline(tmp_path: Path) -> None:
    orchestrator = Orchestrator(root_dir=tmp_path)

    compose_resp = handle_call(orchestrator.compose, make_intent("p_tc_f_005", duration_sec=10))
    assert compose_resp["code"] == 0
    compose_data = compose_resp["data"]

    soundfont = tmp_path / "assets" / "soundfonts" / "piano.sf2"
    soundfont.parent.mkdir(parents=True, exist_ok=True)
    soundfont.write_text("fake sf2", encoding="utf-8")

    render_audio_resp = handle_call(
        orchestrator.render_audio,
        {
            "project_id": "p_tc_f_005",
            "version": compose_data["version"],
            "midi_path": compose_data["midi"],
            "soundfont_path": str(soundfont.relative_to(tmp_path)),
        },
    )
    assert render_audio_resp["code"] == 0
    wav_path = tmp_path / render_audio_resp["data"]["wav_path"]
    assert wav_path.exists()

    render_video_resp = handle_call(
        orchestrator.render_video,
        {
            "project_id": "p_tc_f_005",
            "version": compose_data["version"],
            "musicxml_path": compose_data["musicxml"],
            "wav_path": render_audio_resp["data"]["wav_path"],
            "highlight_scheme": {"played": "#000000", "unplayed": "#C8C8C8"},
        },
    )
    assert render_video_resp["code"] == 0
    mp4_path = tmp_path / render_video_resp["data"]["mp4_path"]
    assert mp4_path.exists()

    export_resp = handle_call(
        orchestrator.export,
        {
            "project_id": "p_tc_f_005",
            "version": compose_data["version"],
            "targets": ["musicxml", "midi", "mp4"],
        },
    )
    assert export_resp["code"] == 0

    export_dir = tmp_path / export_resp["data"]["export_dir"]
    assert (export_dir / "song.musicxml").exists()
    assert (export_dir / "song.mid").exists()
    assert (export_dir / "song.mp4").exists()

    manifest = load_json(tmp_path / export_resp["data"]["manifest_path"])
    assert set(manifest["exports"].keys()) == {"musicxml", "midi", "mp4"}


def test_edit_and_rollback(tmp_path: Path) -> None:
    orchestrator = Orchestrator(root_dir=tmp_path)

    compose_resp = handle_call(orchestrator.compose, make_intent("p_tc_e_003", duration_sec=8))
    assert compose_resp["code"] == 0
    v1 = compose_resp["data"]["version"]
    score_v1 = load_json(tmp_path / compose_resp["data"]["score_json"])
    note_id = score_v1["notes"][0]["note_id"]
    pitch_v1 = score_v1["notes"][0]["pitch"]

    edit1 = handle_call(
        orchestrator.edit_score,
        {
            "project_id": "p_tc_e_003",
            "base_version": v1,
            "edits": [{"note_id": note_id, "type": "pitch_shift", "semitones": 2}],
        },
    )
    assert edit1["code"] == 0
    v2 = edit1["data"]["new_version"]

    edit2 = handle_call(
        orchestrator.edit_score,
        {
            "project_id": "p_tc_e_003",
            "base_version": v2,
            "edits": [{"note_id": note_id, "type": "pitch_shift", "semitones": 2}],
        },
    )
    assert edit2["code"] == 0

    rollback = handle_call(
        orchestrator.rollback,
        {"project_id": "p_tc_e_003", "target_version": v1},
    )
    assert rollback["code"] == 0

    rollback_score = load_json(tmp_path / rollback["data"]["score_json"])
    assert rollback_score["notes"][0]["pitch"] == pitch_v1


def test_rhythm_chord_rest_edits(tmp_path: Path) -> None:
    orchestrator = Orchestrator(root_dir=tmp_path)
    compose_resp = handle_call(orchestrator.compose, make_intent("p_tc_e_rhythm", duration_sec=8))
    assert compose_resp["code"] == 0
    base_version = compose_resp["data"]["version"]
    score = load_json(tmp_path / compose_resp["data"]["score_json"])
    note_id = score["notes"][0]["note_id"]

    set_dur = handle_call(
        orchestrator.edit_score,
        {
            "project_id": "p_tc_e_rhythm",
            "base_version": base_version,
            "edits": [{"note_id": note_id, "type": "set_duration", "dur": "1/2"}],
        },
    )
    assert set_dur["code"] == 0
    v2 = set_dur["data"]["new_version"]
    score_v2 = load_json(tmp_path / set_dur["data"]["score_json"])
    target_v2 = next(n for n in score_v2["notes"] if n["note_id"] == note_id)
    assert target_v2["dur"] == "1/2"

    set_chord = handle_call(
        orchestrator.edit_score,
        {
            "project_id": "p_tc_e_rhythm",
            "base_version": v2,
            "edits": [{"note_id": note_id, "type": "set_pitches", "pitches": ["D4", "F#4", "A4"]}],
        },
    )
    assert set_chord["code"] == 0
    v3 = set_chord["data"]["new_version"]
    score_v3 = load_json(tmp_path / set_chord["data"]["score_json"])
    target_v3 = next(n for n in score_v3["notes"] if n["note_id"] == note_id)
    assert target_v3["pitches"] == ["D4", "F#4", "A4"]
    assert target_v3["is_rest"] is False

    set_rest = handle_call(
        orchestrator.edit_score,
        {
            "project_id": "p_tc_e_rhythm",
            "base_version": v3,
            "edits": [{"note_id": note_id, "type": "toggle_rest", "is_rest": True}],
        },
    )
    assert set_rest["code"] == 0
    score_v4 = load_json(tmp_path / set_rest["data"]["score_json"])
    target_v4 = next(n for n in score_v4["notes"] if n["note_id"] == note_id)
    assert target_v4["is_rest"] is True
    assert target_v4["pitches"] == []


def test_reference_song_similarity_gate(tmp_path: Path) -> None:
    orchestrator = Orchestrator(root_dir=tmp_path)

    reference_path = tmp_path / "assets" / "reference_scores" / "senbonzakura.score.json"
    dump_json(
        reference_path,
        {
            "meta": {
                "time_signature": "4/4",
                "tempo_bpm": 154,
                "key": "D",
                "duration_sec": 8,
                "style": "custom",
                "title": "千本樱",
                "mood": "dramatic",
                "difficulty": "hard",
                "reference": "senbonzakura",
                "bars": 2,
            },
            "notes": [
                {
                    "note_id": "n_000001",
                    "bar": 1,
                    "beat": 1.0,
                    "dur": "1/2",
                    "pitch": "E5",
                    "pitches": ["E5"],
                    "is_rest": False,
                    "staff": 1,
                    "voice": 1,
                    "vel": 86,
                },
                {
                    "note_id": "n_000002",
                    "bar": 1,
                    "beat": 3.0,
                    "dur": "1/4",
                    "pitch": "D5",
                    "pitches": ["D5"],
                    "is_rest": False,
                    "staff": 1,
                    "voice": 1,
                    "vel": 84,
                },
                {
                    "note_id": "n_000003",
                    "bar": 1,
                    "beat": 4.0,
                    "dur": "1/4",
                    "pitch": "C5",
                    "pitches": ["C5"],
                    "is_rest": False,
                    "staff": 1,
                    "voice": 1,
                    "vel": 82,
                },
                {
                    "note_id": "n_000004",
                    "bar": 2,
                    "beat": 1.0,
                    "dur": "1/2",
                    "pitch": "E5",
                    "pitches": ["E5"],
                    "is_rest": False,
                    "staff": 1,
                    "voice": 1,
                    "vel": 86,
                },
                {
                    "note_id": "n_000005",
                    "bar": 2,
                    "beat": 3.0,
                    "dur": "1/4",
                    "pitch": "G5",
                    "pitches": ["G5"],
                    "is_rest": False,
                    "staff": 1,
                    "voice": 1,
                    "vel": 84,
                },
                {
                    "note_id": "n_000006",
                    "bar": 2,
                    "beat": 4.0,
                    "dur": "1/4",
                    "pitch": "A5",
                    "pitches": ["A5"],
                    "is_rest": False,
                    "staff": 1,
                    "voice": 1,
                    "vel": 82,
                },
                {
                    "note_id": "n_000007",
                    "bar": 1,
                    "beat": 1.0,
                    "dur": "1/1",
                    "pitch": "D3",
                    "pitches": ["D3", "A3"],
                    "is_rest": False,
                    "staff": 2,
                    "voice": 1,
                    "vel": 68,
                },
                {
                    "note_id": "n_000008",
                    "bar": 2,
                    "beat": 1.0,
                    "dur": "1/1",
                    "pitch": "C3",
                    "pitches": ["C3", "G3"],
                    "is_rest": False,
                    "staff": 2,
                    "voice": 1,
                    "vel": 68,
                },
            ],
        },
    )

    compose_payload = make_intent("p_tc_ref_song", duration_sec=8)
    compose_payload["title"] = "千本樱"
    compose_payload["target_song"] = "senbonzakura"
    compose_resp = handle_call(orchestrator.compose, compose_payload)
    assert compose_resp["code"] == 0
    assert compose_resp["data"]["compose_engine"] == "reference"
    assert compose_resp["data"]["reference_score"] == "assets/reference_scores/senbonzakura.score.json"

    similarity_resp = handle_call(
        orchestrator.evaluate_similarity,
        {
            "project_id": "p_tc_ref_song",
            "version": compose_resp["data"]["version"],
            "target_song": "senbonzakura",
            "threshold": 95.0,
        },
    )
    assert similarity_resp["code"] == 0
    assert similarity_resp["data"]["pass"] is True
    assert similarity_resp["data"]["similarity"] >= 95.0
    assert (tmp_path / similarity_resp["data"]["report_path"]).exists()


def test_render_audio_retry_and_failure(tmp_path: Path) -> None:
    orchestrator = Orchestrator(root_dir=tmp_path)

    compose_resp = handle_call(orchestrator.compose, make_intent("p_tc_s_001", duration_sec=8))
    assert compose_resp["code"] == 0

    render_audio_resp = handle_call(
        orchestrator.render_audio,
        {
            "project_id": "p_tc_s_001",
            "version": compose_resp["data"]["version"],
            "midi_path": compose_resp["data"]["midi"],
            "soundfont_path": "assets/soundfonts/not_found.sf2",
        },
    )
    assert render_audio_resp["code"] == ERROR_RENDER_AUDIO_FAILED
    render_logs = sorted((tmp_path / "logs" / "render").glob("*.log"))
    assert len(render_logs) == 1
    log_text = render_logs[0].read_text(encoding="utf-8")
    assert "attempt 1 failed" in log_text
    assert "attempt 2 failed" in log_text
