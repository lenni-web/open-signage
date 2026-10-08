"""Gemeinsame Konstanten für die Tests."""

import base64
from pathlib import Path


PROJECT_ROOT = Path(__file__).parents[1]


VALID_PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII="
)
