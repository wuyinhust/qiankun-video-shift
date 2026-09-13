#!/usr/bin/env python3
"""Report media-tool capabilities without installing or changing anything."""

from __future__ import annotations

import argparse
import importlib.util
import json
import subprocess
import sys

from media_tools import resolve_binary


def get_version(path: str | None, name: str) -> str | None:
    if not path:
        return None
    args = [path, "--version"] if name == "yt-dlp" else [path, "-version"]
    try:
        result = subprocess.run(
            args,
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    text = (result.stdout or result.stderr).strip().splitlines()
    return text[0] if text else None


def build_report() -> dict:
    ffmpeg = resolve_binary("ffmpeg", "FFMPEG_BIN")
    ffprobe = resolve_binary("ffprobe", "FFPROBE_BIN")
    ytdlp = resolve_binary("yt-dlp", "YTDLP_BIN")
    opencv = importlib.util.find_spec("cv2") is not None
    return {
        "python": sys.version.split()[0],
        "tools": {
            "ffmpeg": {"path": ffmpeg, "version": get_version(ffmpeg, "ffmpeg")},
            "ffprobe": {"path": ffprobe, "version": get_version(ffprobe, "ffprobe")},
            "yt-dlp": {"path": ytdlp, "version": get_version(ytdlp, "yt-dlp")},
            "opencv": {"available": opencv},
        },
        "capabilities": {
            "local_source_manifest": True,
            "direct_http_download": True,
            "platform_page_download": bool(ytdlp),
            "deterministic_segmentation": bool(ffmpeg and ffprobe),
            "keyframe_extraction": bool(ffmpeg and ffprobe),
            "audio_extraction": bool(ffmpeg and ffprobe),
        },
        "core_ready": bool(ffmpeg and ffprobe),
    }


def print_human(report: dict) -> None:
    print(f"Python: {report['python']}")
    for name, info in report["tools"].items():
        if name == "opencv":
            print(f"OpenCV: {'available' if info['available'] else 'missing'}")
            continue
        status = info["path"] or "missing"
        print(f"{name}: {status}")
    print(f"Core media pipeline: {'ready' if report['core_ready'] else 'not ready'}")
    if not report["capabilities"]["platform_page_download"]:
        print("Platform-page links need yt-dlp; direct video URLs still work.")


def main() -> int:
    parser = argparse.ArgumentParser(description="Check viral-video skill dependencies")
    parser.add_argument("--json", action="store_true", help="print machine-readable JSON")
    parser.add_argument(
        "--require-core",
        action="store_true",
        help="exit 2 unless ffmpeg and ffprobe are available",
    )
    args = parser.parse_args()
    report = build_report()
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    else:
        print_human(report)
    if args.require_core and not report["core_ready"]:
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
