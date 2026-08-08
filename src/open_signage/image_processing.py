from __future__ import annotations

import json
import subprocess
import uuid
from pathlib import Path


def _dimensions(path: Path) -> tuple[int, int]:
    result = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
         "stream=width,height", "-of", "json", str(path)],
        capture_output=True, text=True, check=True,
    )
    stream = json.loads(result.stdout)["streams"][0]
    return int(stream["width"]), int(stream["height"])


def _render(source: Path, target: Path, filters: list[str]) -> None:
    subprocess.run(
        ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-i", str(source),
         "-vf", ",".join(filters), "-frames:v", "1", "-c:v", "mjpeg",
         "-q:v", "3", str(target)],
        capture_output=True, check=True,
    )


def _outputs(source: Path, directory: Path, filters: list[str]) -> dict:
    optimized = directory / f"{uuid.uuid4().hex}-display.jpg"
    thumbnail = directory / f"{uuid.uuid4().hex}-thumb.jpg"
    _render(source, optimized, [*filters, "scale=1920:1080:force_original_aspect_ratio=decrease"])
    _render(optimized, thumbnail, ["scale=480:270:force_original_aspect_ratio=decrease"])
    width, height = _dimensions(optimized)
    return {
        "source": f"/media/{optimized.name}", "thumbnail_source": f"/media/{thumbnail.name}",
        "width": width, "height": height,
    }


def optimize_image(original: Path, directory: Path) -> dict:
    return _outputs(original, directory, [])


def edit_image(
    original: Path, directory: Path, *, rotate: int = 0, crop_16_9: bool = False,
    focus_x: int = 50, focus_y: int = 50, brightness: float = 1.0,
    contrast: float = 1.0,
) -> dict:
    width, height = _dimensions(original)
    filters: list[str] = []
    if rotate in {90, 270}:
        filters.append("transpose=1" if rotate == 90 else "transpose=2")
        width, height = height, width
    elif rotate == 180:
        filters.extend(["hflip", "vflip"])
    if crop_16_9:
        if width / height > 16 / 9:
            crop_width = round(height * 16 / 9)
            left = round((width - crop_width) * focus_x / 100)
            filters.append(f"crop={crop_width}:{height}:{left}:0")
        else:
            crop_height = round(width * 9 / 16)
            top = round((height - crop_height) * focus_y / 100)
            filters.append(f"crop={width}:{crop_height}:0:{top}")
    filters.append(f"eq=brightness={brightness - 1:.3f}:contrast={contrast:.3f}")
    return _outputs(original, directory, filters)
