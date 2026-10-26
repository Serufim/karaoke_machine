"""Inspect media streams without decoding or creating intermediate video files."""
import json
import math
import shutil
import subprocess
from pathlib import Path
from typing import Any, Dict


def probe_media(path: Path, ffmpeg_bin: str) -> Dict[str, Any]:
    sibling = Path(ffmpeg_bin).with_name("ffprobe")
    ffprobe = str(sibling) if sibling.is_file() else shutil.which("ffprobe")
    if not ffprobe:
        raise RuntimeError("Не найден ffprobe. Установите FFmpeg вместе с ffprobe.")
    result = subprocess.run(
        [ffprobe, "-v", "error", "-show_streams", "-show_format", "-of", "json", str(path)],
        capture_output=True, text=True, timeout=30,
    )
    if result.returncode:
        raise ValueError(f"Не удалось прочитать медиафайл {path.name}: {result.stderr[-1000:]}")
    return json.loads(result.stdout)


def video_streams(metadata: Dict[str, Any]):
    format_name = metadata.get("format", {}).get("format_name", "")
    if format_name == "image2" or format_name.endswith("_pipe") or format_name in ("gif", "apng"):
        return []
    return [s for s in metadata.get("streams", [])
            if s.get("codec_type") == "video" and not s.get("disposition", {}).get("attached_pic")]


def audio_duration(metadata: Dict[str, Any]) -> float:
    streams = [s for s in metadata.get("streams", []) if s.get("codec_type") == "audio"]
    if not streams:
        raise ValueError("В источнике песни нет аудиодорожки.")
    duration = float(streams[0].get("duration") or metadata.get("format", {}).get("duration") or 0)
    if not math.isfinite(duration) or duration <= 0:
        raise ValueError("Не удалось определить положительную длительность аудиодорожки.")
    return duration
