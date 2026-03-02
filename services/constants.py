from __future__ import annotations

from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent
PROJECTS_DIR = ROOT_DIR / "projects"
LOGS_DIR = ROOT_DIR / "logs"
TASK_LOG_DIR = LOGS_DIR / "tasks"
RENDER_LOG_DIR = LOGS_DIR / "render"
EXPORT_LOG_DIR = LOGS_DIR / "export"
ASSETS_DIR = ROOT_DIR / "assets"
DEFAULT_SOUNDFONT = ASSETS_DIR / "soundfonts" / "piano.sf2"

MAX_DURATION_SEC = 60
MAX_LLM_RETRY = 3
MAX_RENDER_RETRY = 2

SAMPLE_RATE = 48_000
WAV_CHANNELS = 2
WAV_WIDTH_BYTES = 2

ERROR_INVALID_PARAMS = 1001
ERROR_DURATION_EXCEEDED = 1002
ERROR_COMPOSE_FAILED = 2001
ERROR_COMPILE_FAILED = 3001
ERROR_RENDER_AUDIO_FAILED = 4001
ERROR_RENDER_VIDEO_FAILED = 4002
ERROR_EXPORT_FAILED = 5001

TASK_STAGES = {
    "compose",
    "compile",
    "render_audio",
    "render_video",
    "export",
    "edit",
    "rollback",
}

TASK_STATUS = {"queued", "running", "success", "failed"}

for directory in (PROJECTS_DIR, TASK_LOG_DIR, RENDER_LOG_DIR, EXPORT_LOG_DIR):
    directory.mkdir(parents=True, exist_ok=True)
