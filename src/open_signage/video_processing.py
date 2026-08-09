from __future__ import annotations

import json
import subprocess
import uuid
from pathlib import Path


def video_metadata(path: Path) -> dict:
    result = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries",
         "format=duration:stream=codec_type,codec_name,width,height", "-of", "json", str(path)],
        capture_output=True, text=True, check=True, timeout=30,
    )
    probe = json.loads(result.stdout)
    video = next((item for item in probe.get("streams", []) if item.get("codec_type") == "video"), {})
    audio = next((item for item in probe.get("streams", []) if item.get("codec_type") == "audio"), {})
    return {
        "width": video.get("width"), "height": video.get("height"),
        "duration_seconds": round(float(probe.get("format", {}).get("duration", 0)), 2),
        "video_codec": video.get("codec_name"), "audio_codec": audio.get("codec_name"),
    }


def video_thumbnail(path: Path, directory: Path) -> str:
    target = directory / f"{uuid.uuid4().hex}-video-thumb.jpg"
    subprocess.run(
        ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-i", str(path),
         "-vf", "thumbnail,scale=480:270:force_original_aspect_ratio=decrease",
         "-frames:v", "1", "-threads", "2", "-c:v", "mjpeg", "-q:v", "4", str(target)],
        capture_output=True, check=True, timeout=120,
    )
    return f"/media/{target.name}"


def transcode_video(path: Path, directory: Path) -> tuple[str, dict, str]:
    target = directory / f"{uuid.uuid4().hex}-converted.mp4"
    subprocess.run(
        ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-i", str(path),
         "-threads", "2", "-c:v", "libx264", "-preset", "veryfast", "-crf", "23", "-pix_fmt", "yuv420p",
         "-c:a", "aac", "-b:a", "160k", "-movflags", "+faststart", str(target)],
        capture_output=True, check=True, timeout=1800,
    )
    return f"/media/{target.name}", video_metadata(target), video_thumbnail(target, directory)
