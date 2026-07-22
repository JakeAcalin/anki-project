"""Local speech-to-text via faster-whisper. Runs fully offline once the model
weights are cached (downloaded on first use)."""
import threading
from pathlib import Path

from .. import config

_model = None
_model_lock = threading.Lock()


def _get_model():
    global _model
    if _model is None:
        with _model_lock:
            if _model is None:
                from faster_whisper import WhisperModel

                _model = WhisperModel(
                    config.WHISPER_MODEL_SIZE,
                    device=config.WHISPER_DEVICE,
                    compute_type=config.WHISPER_COMPUTE_TYPE,
                )
    return _model


def transcribe(audio_path: Path) -> str:
    """Transcribe an audio file to plain text using local Whisper."""
    model = _get_model()
    segments, _info = model.transcribe(str(audio_path), vad_filter=True)
    return " ".join(segment.text.strip() for segment in segments).strip()
