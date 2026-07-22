import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = Path(os.environ.get("ANKI_APP_DATA_DIR", BASE_DIR / "data"))
UPLOAD_DIR = DATA_DIR / "uploads"
MEDIA_DIR = DATA_DIR / "media"
EXPORT_DIR = DATA_DIR / "exports"
PROJECT_FILE = DATA_DIR / "project.json"

for d in (DATA_DIR, UPLOAD_DIR, MEDIA_DIR, EXPORT_DIR):
    d.mkdir(parents=True, exist_ok=True)

ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
CLAUDE_TEXT_MODEL = os.environ.get("CLAUDE_TEXT_MODEL", "claude-sonnet-5")
CLAUDE_VISION_MODEL = os.environ.get("CLAUDE_VISION_MODEL", "claude-sonnet-5")

WHISPER_MODEL_SIZE = os.environ.get("WHISPER_MODEL_SIZE", "small")
WHISPER_DEVICE = os.environ.get("WHISPER_DEVICE", "cpu")
WHISPER_COMPUTE_TYPE = os.environ.get("WHISPER_COMPUTE_TYPE", "int8")

VIDEO_FRAME_INTERVAL_SECONDS = float(os.environ.get("VIDEO_FRAME_INTERVAL_SECONDS", "15"))
VIDEO_MAX_FRAMES = int(os.environ.get("VIDEO_MAX_FRAMES", "12"))

MAX_UPLOAD_MB = int(os.environ.get("MAX_UPLOAD_MB", "500"))

HOST = os.environ.get("ANKI_APP_HOST", "127.0.0.1")
PORT = int(os.environ.get("ANKI_APP_PORT", "8000"))
