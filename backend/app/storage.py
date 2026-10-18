"""Temporary-file helpers. Only files whose names look like our own
random hex names are ever deleted, so a mis-set OUTPUT_DIR cannot wipe user data."""
import os
import re
import time
import uuid
from pathlib import Path

_SAFE_NAME = re.compile(r"^[0-9a-f]{32}\.(wav|mp3|flac|ogg|m4a)$")


def new_temp_path(directory: Path, ext: str) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    return directory / f"{uuid.uuid4().hex}{ext}"


def remove_quietly(path: Path) -> None:
    try:
        if _SAFE_NAME.match(path.name):
            os.remove(path)
    except OSError:
        pass


def cleanup_dir(directory: Path, max_age_seconds: float) -> int:
    """Delete our own stale files (age >= max_age_seconds). Returns count removed."""
    removed, now = 0, time.time()
    if not directory.is_dir():
        return 0
    for p in directory.rglob("*"):
        try:
            if p.is_file() and _SAFE_NAME.match(p.name) and now - p.stat().st_mtime >= max_age_seconds:
                os.remove(p)
                removed += 1
        except OSError:
            continue
    return removed
