from __future__ import annotations

import argparse
import json
from pathlib import Path

from services.orchestrator import Orchestrator, handle_call


def print_response(response: dict) -> None:
    print(json.dumps(response, ensure_ascii=False, indent=2))


def main() -> None:
    parser = argparse.ArgumentParser(description="Piano for AI desktop CLI")
    parser.add_argument("--root-dir", default=str(Path(__file__).resolve().parent.parent))

    subparsers = parser.add_subparsers(dest="command", required=True)

    compose = subparsers.add_parser("compose")
    compose.add_argument("--project-id", required=True)
    compose.add_argument("--title", required=True)
    compose.add_argument("--style", default="ancient_cn")
    compose.add_argument("--mood", default="calm")
    compose.add_argument("--tempo-bpm", type=int, default=88)
    compose.add_argument("--key", default="D")
    compose.add_argument("--duration-sec", type=int, default=60)
    compose.add_argument("--difficulty", default="medium")
    compose.add_argument("--reference", default="古风、空灵、可演奏")
    compose.add_argument(
        "--compose-mode",
        default="auto",
        choices=["auto", "ai", "rule"],
        help="auto: AI if configured, else rule; ai: force AI; rule: deterministic composer",
    )
    compose.add_argument("--target-song", default="")
    compose.add_argument("--reference-score-path", default="")
    compose.add_argument("--reference-midi-path", default="")
    compose.add_argument("--ai-provider", default="")
    compose.add_argument("--ai-model", default="")
    compose.add_argument("--ai-base-url", default="")
    compose.add_argument("--ai-api-key", default="")

    render_audio = subparsers.add_parser("render-audio")
    render_audio.add_argument("--project-id", required=True)
    render_audio.add_argument("--version", required=True)
    render_audio.add_argument("--midi-path", required=True)
    render_audio.add_argument("--soundfont-path", required=True)

    render_video = subparsers.add_parser("render-video")
    render_video.add_argument("--project-id", required=True)
    render_video.add_argument("--version", required=True)
    render_video.add_argument("--musicxml-path", required=True)
    render_video.add_argument("--wav-path", required=True)

    edit = subparsers.add_parser("edit")
    edit.add_argument("--project-id", required=True)
    edit.add_argument("--base-version", required=True)
    edit.add_argument("--note-id", required=True)
    edit.add_argument("--semitones", type=int, default=0)

    rollback = subparsers.add_parser("rollback")
    rollback.add_argument("--project-id", required=True)
    rollback.add_argument("--target-version", required=True)

    export = subparsers.add_parser("export")
    export.add_argument("--project-id", required=True)
    export.add_argument("--version", required=True)
    export.add_argument(
        "--targets",
        nargs="+",
        default=["musicxml", "midi", "mp4"],
        choices=["musicxml", "midi", "mp4"],
    )

    evaluate_similarity = subparsers.add_parser("evaluate-similarity")
    evaluate_similarity.add_argument("--project-id", required=True)
    evaluate_similarity.add_argument("--version", required=True)
    evaluate_similarity.add_argument("--target-song", default="")
    evaluate_similarity.add_argument("--reference-score-path", default="")
    evaluate_similarity.add_argument("--reference-midi-path", default="")
    evaluate_similarity.add_argument("--threshold", type=float, default=95.0)

    args = parser.parse_args()
    orchestrator = Orchestrator(root_dir=Path(args.root_dir).resolve())

    if args.command == "compose":
        payload = {
            "project_id": args.project_id,
            "title": args.title,
            "style": args.style,
            "mood": args.mood,
            "tempo_bpm": args.tempo_bpm,
            "key": args.key,
            "duration_sec": args.duration_sec,
            "difficulty": args.difficulty,
            "reference": args.reference,
            "compose_mode": args.compose_mode,
            "target_song": args.target_song,
            "reference_score_path": args.reference_score_path,
            "reference_midi_path": args.reference_midi_path,
            "ai_provider": args.ai_provider,
            "ai_model": args.ai_model,
            "ai_base_url": args.ai_base_url,
            "ai_api_key": args.ai_api_key,
        }
        print_response(handle_call(orchestrator.compose, payload))
        return

    if args.command == "render-audio":
        payload = {
            "project_id": args.project_id,
            "version": args.version,
            "midi_path": args.midi_path,
            "soundfont_path": args.soundfont_path,
        }
        print_response(handle_call(orchestrator.render_audio, payload))
        return

    if args.command == "render-video":
        payload = {
            "project_id": args.project_id,
            "version": args.version,
            "musicxml_path": args.musicxml_path,
            "wav_path": args.wav_path,
            "highlight_scheme": {"played": "#000000", "unplayed": "#C8C8C8"},
        }
        print_response(handle_call(orchestrator.render_video, payload))
        return

    if args.command == "edit":
        payload = {
            "project_id": args.project_id,
            "base_version": args.base_version,
            "edits": [
                {
                    "note_id": args.note_id,
                    "type": "pitch_shift",
                    "semitones": args.semitones,
                }
            ],
        }
        print_response(handle_call(orchestrator.edit_score, payload))
        return

    if args.command == "rollback":
        payload = {"project_id": args.project_id, "target_version": args.target_version}
        print_response(handle_call(orchestrator.rollback, payload))
        return

    if args.command == "export":
        payload = {
            "project_id": args.project_id,
            "version": args.version,
            "targets": args.targets,
        }
        print_response(handle_call(orchestrator.export, payload))
        return

    if args.command == "evaluate-similarity":
        payload = {
            "project_id": args.project_id,
            "version": args.version,
            "target_song": args.target_song,
            "reference_score_path": args.reference_score_path,
            "reference_midi_path": args.reference_midi_path,
            "threshold": args.threshold,
        }
        print_response(handle_call(orchestrator.evaluate_similarity, payload))
        return


if __name__ == "__main__":
    main()
