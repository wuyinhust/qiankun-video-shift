#!/usr/bin/env python3
"""Resolve media executables from explicit, standard, and existing Codex locations."""

from __future__ import annotations

import os
from pathlib import Path
import shutil


def _usable(path: Path) -> str | None:
    try:
        if path.is_file() and os.access(path, os.X_OK):
            return str(path.resolve())
    except OSError:
        return None
    return None


def _bundled_candidates(name: str):
    roots = [Path.home() / ".codex" / "skills", Path.home() / ".agents" / "skills"]
    patterns = {
        "ffmpeg": [
            "*/node_modules/ffmpeg-static/ffmpeg",
            "*/node_modules/.pnpm/ffmpeg-static@*/node_modules/ffmpeg-static/ffmpeg",
        ],
        "ffprobe": [
            "*/node_modules/@ffprobe-installer/ffprobe",
            "*/node_modules/.pnpm/@derhuerst+ffprobe-static@*/node_modules/@derhuerst/ffprobe-static/ffprobe",
        ],
    }
    for root in roots:
        if not root.is_dir():
            continue
        for pattern in patterns.get(name, []):
            yield from root.glob(pattern)


def resolve_binary(name: str, env_name: str) -> str | None:
    configured = os.environ.get(env_name)
    if configured:
        resolved = _usable(Path(configured).expanduser())
        if resolved:
            return resolved

    found = shutil.which(name)
    if found:
        resolved = _usable(Path(found))
        if resolved:
            return resolved

    common = [
        Path.home() / ".local" / "bin" / name,
        Path("/opt/homebrew/bin") / name,
        Path("/usr/local/bin") / name,
    ]
    for candidate in common:
        resolved = _usable(candidate)
        if resolved:
            return resolved

    for candidate in _bundled_candidates(name):
        resolved = _usable(candidate)
        if resolved:
            return resolved
    return None
