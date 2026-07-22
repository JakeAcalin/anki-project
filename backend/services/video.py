"""ffmpeg-based helpers: pull the audio track out of a video for transcription,
and sample keyframes so they can be offered as answer-side images."""
import json
import subprocess
from pathlib import Path
from typing import List, Tuple

from .. import config


class FFmpegError(RuntimeError):
    pass


def _run(cmd: List[str]) -> None:
    result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if result.returncode != 0:
        raise FFmpegError(result.stderr.decode("utf-8", errors="replace")[-2000:])


def get_duration_seconds(video_path: Path) -> float:
    cmd = [
        "ffprobe", "-v", "error", "-show_entries", "format=duration",
        "-of", "json", str(video_path),
    ]
    result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if result.returncode != 0:
        raise FFmpegError(result.stderr.decode("utf-8", errors="replace")[-2000:])
    data = json.loads(result.stdout.decode("utf-8"))
    return float(data.get("format", {}).get("duration", 0.0))


def extract_audio(video_path: Path, out_dir: Path) -> Path:
    out_path = out_dir / f"{video_path.stem}_audio.wav"
    cmd = [
        "ffmpeg", "-y", "-i", str(video_path),
        "-vn", "-ac", "1", "-ar", "16000", "-f", "wav", str(out_path),
    ]
    _run(cmd)
    return out_path


def extract_keyframes(video_path: Path, out_dir: Path) -> List[Tuple[Path, float]]:
    """Sample frames at a fixed interval, capped at VIDEO_MAX_FRAMES, evenly
    spread across the video if that cap would otherwise be exceeded."""
    duration = get_duration_seconds(video_path)
    if duration <= 0:
        return []

    interval = config.VIDEO_FRAME_INTERVAL_SECONDS
    est_frames = duration / interval
    if est_frames > config.VIDEO_MAX_FRAMES:
        interval = duration / config.VIDEO_MAX_FRAMES

    pattern = out_dir / f"{video_path.stem}_frame_%04d.jpg"
    cmd = [
        "ffmpeg", "-y", "-i", str(video_path),
        "-vf", f"fps=1/{interval}",
        "-vsync", "vfr", "-q:v", "3",
        str(pattern),
    ]
    _run(cmd)

    frames = sorted(out_dir.glob(f"{video_path.stem}_frame_*.jpg"))
    results = []
    for i, frame_path in enumerate(frames[: config.VIDEO_MAX_FRAMES]):
        timestamp = round(i * interval, 2)
        results.append((frame_path, timestamp))
    return results
