from __future__ import annotations

import json
import subprocess
from pathlib import Path

RECOMMENDATION = (
    "Empfohlen: MP4 mit H.264/AVC und AAC. Alternativ: WebM mit VP8/VP9 "
    "und Opus/Vorbis."
)


def evaluate_video_probe(suffix: str, probe: dict) -> dict:
    streams = probe.get("streams", [])
    format_names = set(probe.get("format", {}).get("format_name", "").split(","))
    video_codecs = [
        stream.get("codec_name", "unbekannt")
        for stream in streams
        if stream.get("codec_type") == "video"
    ]
    audio_codecs = [
        stream.get("codec_name", "unbekannt")
        for stream in streams
        if stream.get("codec_type") == "audio"
    ]
    video_streams = [stream for stream in streams if stream.get("codec_type") == "video"]
    try:
        duration = float(probe.get("format", {}).get("duration", 0))
    except (TypeError, ValueError):
        duration = 0
    warnings: list[str] = []

    if not video_codecs:
        warnings.append("Die Datei enthält keine erkennbare Videospur.")
    elif suffix == ".mp4":
        if not format_names.intersection({"mov", "mp4", "m4a", "3gp", "3g2", "mj2"}):
            warnings.append("Der Dateiinhalt ist kein gültiger MP4-Container.")
        if any(codec != "h264" for codec in video_codecs):
            warnings.append(
                f"MP4-Video-Codec nicht empfohlen: {', '.join(video_codecs)}. "
                "Für zuverlässige Wiedergabe H.264/AVC verwenden."
            )
        unsupported_audio = [codec for codec in audio_codecs if codec != "aac"]
        if unsupported_audio:
            warnings.append(
                f"MP4-Audio-Codec nicht empfohlen: {', '.join(unsupported_audio)}. "
                "AAC verwenden."
            )
    elif suffix == ".webm":
        if "webm" not in format_names:
            warnings.append("Der Dateiinhalt ist kein gültiger WebM-Container.")
        unsupported_video = [codec for codec in video_codecs if codec not in {"vp8", "vp9"}]
        if unsupported_video:
            warnings.append(
                f"WebM-Video-Codec nicht empfohlen: {', '.join(unsupported_video)}. "
                "VP8 oder VP9 verwenden."
            )
        unsupported_audio = [
            codec for codec in audio_codecs if codec not in {"opus", "vorbis"}
        ]
        if unsupported_audio:
            warnings.append(
                f"WebM-Audio-Codec nicht empfohlen: {', '.join(unsupported_audio)}. "
                "Opus oder Vorbis verwenden."
            )

    return {
        "checked": True,
        "compatible": not warnings,
        "container": ",".join(sorted(format_names)) or "unbekannt",
        "video_codecs": video_codecs,
        "audio_codecs": audio_codecs,
        "duration_seconds": duration,
        "width": video_streams[0].get("width") if video_streams else None,
        "height": video_streams[0].get("height") if video_streams else None,
        "warnings": warnings,
        "recommendation": RECOMMENDATION,
    }


def inspect_video(path: Path) -> dict:
    try:
        result = subprocess.run(
            [
                "ffprobe",
                "-v",
                "error",
                "-show_entries",
                "format=format_name,duration:stream=codec_type,codec_name,width,height,duration",
                "-of",
                "json",
                str(path),
            ],
            capture_output=True,
            check=True,
            text=True,
            timeout=30,
        )
        probe = json.loads(result.stdout)
    except FileNotFoundError:
        return {
            "checked": False,
            "compatible": None,
            "warnings": ["Videoformat konnte nicht geprüft werden: ffprobe fehlt."],
            "recommendation": RECOMMENDATION,
        }
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired, json.JSONDecodeError):
        return {
            "checked": False,
            "compatible": False,
            "warnings": ["Die Videodatei konnte nicht zuverlässig analysiert werden."],
            "recommendation": RECOMMENDATION,
        }

    return evaluate_video_probe(path.suffix.lower(), probe)


def validate_video(path: Path) -> dict:
    """Reject unreadable containers and files without a usable video stream."""
    result = inspect_video(path)
    if (
        not result.get("checked")
        or not result.get("video_codecs")
        or not result.get("duration_seconds")
        or not result.get("width")
        or not result.get("height")
    ):
        raise ValueError("Keine gültige und vollständig lesbare Videospur gefunden")
    return result
