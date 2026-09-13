#!/usr/bin/env python3
"""Deterministically detect shots and extract timestamped evidence frames with FFmpeg."""

from __future__ import annotations

import argparse
from fractions import Fraction
import hashlib
import html
import json
import math
from pathlib import Path
import re
import shutil
import subprocess
import sys

from media_tools import resolve_binary


class SegmentError(RuntimeError):
    def __init__(self, message: str, exit_code: int = 1):
        super().__init__(message)
        self.exit_code = exit_code


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def run(command: list[str], label: str) -> subprocess.CompletedProcess:
    result = subprocess.run(command, capture_output=True, text=True, check=False)
    if result.returncode != 0:
        lines = (result.stderr or result.stdout).strip().splitlines()
        detail = lines[-1] if lines else f"exit {result.returncode}"
        raise SegmentError(f"{label}失败：{detail}", 2)
    return result


def parse_rate(value: str | None) -> float | None:
    if not value or value in {"0/0", "N/A"}:
        return None
    try:
        return float(Fraction(value))
    except (ValueError, ZeroDivisionError):
        return None


def probe_video(ffprobe: str, video: Path) -> dict:
    result = run(
        [
            ffprobe,
            "-v", "error",
            "-show_streams",
            "-show_format",
            "-of", "json",
            str(video),
        ],
        "ffprobe",
    )
    try:
        raw = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise SegmentError(f"ffprobe 返回无效 JSON：{exc}", 2) from exc
    video_stream = next((item for item in raw.get("streams", []) if item.get("codec_type") == "video"), None)
    if not video_stream:
        raise SegmentError("文件中没有视频流", 2)
    audio_streams = [item for item in raw.get("streams", []) if item.get("codec_type") == "audio"]
    duration_raw = raw.get("format", {}).get("duration") or video_stream.get("duration")
    try:
        duration = float(duration_raw)
    except (TypeError, ValueError) as exc:
        raise SegmentError("无法确定视频时长", 2) from exc
    width = int(video_stream.get("width") or 0)
    height = int(video_stream.get("height") or 0)
    gcd = math.gcd(width, height) if width and height else 0
    return {
        "duration_s": round(duration, 3),
        "width": width,
        "height": height,
        "aspect_ratio": f"{width // gcd}:{height // gcd}" if gcd else "unknown",
        "fps": round(parse_rate(video_stream.get("avg_frame_rate")) or 0.0, 3),
        "video_codec": video_stream.get("codec_name") or "unknown",
        "audio_stream_count": len(audio_streams),
        "format_name": raw.get("format", {}).get("format_name") or "unknown",
        "bit_rate": int(raw.get("format", {}).get("bit_rate") or 0),
    }


def detect_scene_times(ffmpeg: str, video: Path, duration: float, threshold: float) -> list[float]:
    expression = f"select='gt(scene,{threshold:.4f})',showinfo"
    result = run(
        [
            ffmpeg,
            "-hide_banner",
            "-loglevel", "info",
            "-nostdin",
            "-i", str(video),
            "-t", f"{duration:.3f}",
            "-vf", expression,
            "-an",
            "-sn",
            "-f", "null",
            "-",
        ],
        "场景检测",
    )
    matches = re.findall(r"pts_time:([0-9]+(?:\.[0-9]+)?)", result.stderr)
    times = sorted({round(float(value), 3) for value in matches})
    return [value for value in times if 0.0 < value < duration]


def build_shots(scene_times: list[float], duration: float, min_shot: float) -> list[tuple[float, float]]:
    boundaries = [0.0] + scene_times + [round(duration, 3)]
    raw = [
        (boundaries[index], boundaries[index + 1])
        for index in range(len(boundaries) - 1)
        if boundaries[index + 1] - boundaries[index] > 0.001
    ]
    merged: list[tuple[float, float]] = []
    for start, end in raw:
        if merged and end - start < min_shot:
            merged[-1] = (merged[-1][0], end)
        else:
            merged.append((start, end))
    if len(merged) > 1 and merged[0][1] - merged[0][0] < min_shot:
        merged[1] = (merged[0][0], merged[1][1])
        merged.pop(0)
    return [(round(start, 3), round(end, 3)) for start, end in merged]


def adaptive_shots(
    ffmpeg: str,
    video: Path,
    duration: float,
    requested_threshold: float,
    min_shot: float,
    max_shots: int,
) -> tuple[list[tuple[float, float]], float, list[float]]:
    threshold = requested_threshold
    while True:
        scene_times = detect_scene_times(ffmpeg, video, duration, threshold)
        shots = build_shots(scene_times, duration, min_shot)
        if len(shots) <= max_shots:
            return shots, round(threshold, 3), scene_times
        threshold = round(threshold + 0.05, 3)
        if threshold > 0.8:
            raise SegmentError(
                f"检测到 {len(shots)} 个镜头，超过 --max-shots={max_shots}；请提高阈值或上限",
                2,
            )


def frame_positions(
    start: float,
    end: float,
    extra_interval: float,
    max_frames: int,
) -> list[tuple[str, float]]:
    duration = end - start
    inset = min(0.10, max(0.01, duration * 0.10))
    candidates: list[tuple[str, float]] = [
        ("start", min(end, start + inset)),
        ("middle", start + duration / 2.0),
        ("end", max(start, end - inset)),
    ]
    if extra_interval > 0 and duration > extra_interval * 1.5:
        cursor = start + extra_interval
        extra_index = 1
        while cursor < end - inset and len(candidates) < max_frames + 3:
            candidates.append((f"extra_{extra_index:02d}", cursor))
            cursor += extra_interval
            extra_index += 1
    candidates.sort(key=lambda item: item[1])
    unique: list[tuple[str, float]] = []
    for role, timestamp in candidates:
        timestamp = round(max(start, min(timestamp, end)), 3)
        if any(abs(timestamp - existing[1]) < 0.04 for existing in unique):
            continue
        unique.append((role, timestamp))
    if len(unique) > max_frames:
        keep = [unique[0], unique[len(unique) // 2], unique[-1]]
        for item in unique:
            if len(keep) >= max_frames:
                break
            if item not in keep:
                keep.append(item)
        unique = sorted(keep, key=lambda item: item[1])
    return unique


def extract_frame(ffmpeg: str, video: Path, timestamp: float, destination: Path, force: bool) -> None:
    command = [
        ffmpeg,
        "-hide_banner",
        "-loglevel", "error",
        "-nostdin",
        "-i", str(video),
        "-ss", f"{timestamp:.3f}",
        "-frames:v", "1",
        "-q:v", "2",
    ]
    command.append("-y" if force else "-n")
    command.append(str(destination))
    run(command, f"抽帧 {timestamp:.3f}s")


def extract_clip(
    ffmpeg: str,
    video: Path,
    start: float,
    end: float,
    destination: Path,
    force: bool,
) -> str | None:
    overwrite = "-y" if force else "-n"
    primary = [
        ffmpeg,
        "-hide_banner", "-loglevel", "error", "-nostdin",
        "-ss", f"{start:.3f}",
        "-i", str(video),
        "-t", f"{end - start:.3f}",
        "-map", "0:v:0", "-map", "0:a?",
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
        "-c:a", "aac", "-movflags", "+faststart",
        overwrite,
        str(destination),
    ]
    result = subprocess.run(primary, capture_output=True, text=True, check=False)
    if result.returncode == 0:
        return None
    fallback = [
        ffmpeg,
        "-hide_banner", "-loglevel", "error", "-nostdin",
        "-ss", f"{start:.3f}",
        "-i", str(video),
        "-t", f"{end - start:.3f}",
        "-map", "0:v:0", "-map", "0:a?",
        "-c", "copy", "-avoid_negative_ts", "make_zero",
        overwrite,
        str(destination),
    ]
    fallback_result = subprocess.run(fallback, capture_output=True, text=True, check=False)
    if fallback_result.returncode == 0:
        return "clip re-encode failed; stream-copy fallback used"
    destination.unlink(missing_ok=True)
    lines = (fallback_result.stderr or result.stderr).strip().splitlines()
    return f"clip extraction failed: {lines[-1] if lines else 'unknown error'}"


def extract_audio(
    ffmpeg: str,
    video: Path,
    destination: Path,
    duration: float,
    force: bool,
) -> None:
    run(
        [
            ffmpeg,
            "-hide_banner", "-loglevel", "error", "-nostdin",
            "-i", str(video),
            "-t", f"{duration:.3f}",
            "-map", "0:a:0",
            "-vn", "-ac", "1", "-ar", "16000", "-c:a", "pcm_s16le",
            "-y" if force else "-n",
            str(destination),
        ],
        "音频提取",
    )


def prepare_output(output_dir: Path, force: bool) -> tuple[Path, Path]:
    owned = [
        output_dir / "shot_manifest.json",
        output_dir / "frame_index.html",
        output_dir / "audio.wav",
        output_dir / "frames",
        output_dir / "clips",
    ]
    existing = [path for path in owned if path.exists()]
    if existing and not force:
        raise SegmentError(
            f"输出目录已有脚本产物：{existing[0]}；请换目录或使用 --force",
            4,
        )
    if force:
        for path in existing:
            if path.is_dir():
                shutil.rmtree(path)
            else:
                path.unlink()
    frames = output_dir / "frames"
    clips = output_dir / "clips"
    output_dir.mkdir(parents=True, exist_ok=True)
    frames.mkdir(parents=True, exist_ok=True)
    return frames, clips


def write_frame_index(output_dir: Path, shots: list[dict]) -> Path:
    blocks = []
    for shot in shots:
        images = []
        for frame in shot["keyframes"]:
            relative = Path(frame["path"]).resolve().relative_to(output_dir.resolve())
            images.append(
                "<figure><img loading='lazy' src='{}' alt='{}'><figcaption>{} · {:.3f}s</figcaption></figure>".format(
                    html.escape(relative.as_posix()),
                    html.escape(shot["shot_id"]),
                    html.escape(frame["role"]),
                    frame["time_s"],
                )
            )
        blocks.append(
            "<section><h2>{}</h2><p>{:.3f}s–{:.3f}s · {:.3f}s</p><div class='frames'>{}</div></section>".format(
                html.escape(shot["shot_id"]),
                shot["start_s"],
                shot["end_s"],
                shot["duration_s"],
                "".join(images),
            )
        )
    document = """<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>分镜关键帧索引</title><style>
body{{font-family:system-ui,sans-serif;margin:24px;background:#f5f3ee;color:#181816}}section{{margin:0 0 32px;padding:18px;background:white;border-radius:14px}}h2{{margin:0}}.frames{{display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:12px}}figure{{margin:0}}img{{width:100%;height:auto;border-radius:8px;background:#ddd}}figcaption{{font-size:13px;color:#555;margin-top:5px}}
</style></head><body><h1>分镜关键帧索引</h1>{}</body></html>""".format("".join(blocks))
    path = output_dir / "frame_index.html"
    path.write_text(document, encoding="utf-8")
    return path


def main() -> int:
    parser = argparse.ArgumentParser(description="Detect shots and extract evidence frames")
    parser.add_argument("video", type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--scene-threshold", type=float, default=0.35)
    parser.add_argument("--min-shot-seconds", type=float, default=0.50)
    parser.add_argument("--max-seconds", type=float, default=120.0)
    parser.add_argument("--max-shots", type=int, default=80)
    parser.add_argument("--max-frames-per-shot", type=int, default=9)
    parser.add_argument("--extra-frame-interval", type=float, default=0.0)
    parser.add_argument("--extract-clips", action="store_true")
    parser.add_argument("--no-audio", action="store_true")
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()

    try:
        video = args.video.expanduser().resolve(strict=True)
        if not video.is_file():
            raise SegmentError(f"输入不是文件：{video}", 2)
        if not 0.0 < args.scene_threshold <= 1.0:
            raise SegmentError("--scene-threshold 必须位于 (0, 1]", 1)
        if args.min_shot_seconds <= 0 or args.max_shots < 1:
            raise SegmentError("镜头时长与镜头上限必须为正数", 1)
        if args.max_frames_per_shot < 3:
            raise SegmentError("--max-frames-per-shot 不能小于 3（首帧、中帧、尾帧）", 1)
        if args.extra_frame_interval < 0:
            raise SegmentError("--extra-frame-interval 不能为负数", 1)
        if args.max_seconds < 0:
            raise SegmentError("--max-seconds 不能为负数；0 表示不限", 1)
        ffmpeg = resolve_binary("ffmpeg", "FFMPEG_BIN")
        ffprobe = resolve_binary("ffprobe", "FFPROBE_BIN")
        if not ffmpeg or not ffprobe:
            raise SegmentError(
                "缺少 ffmpeg 或 ffprobe；将其加入 PATH，或设置 FFMPEG_BIN/FFPROBE_BIN",
                2,
            )
        frames_dir, clips_dir = prepare_output(args.output_dir, args.force)
        technical = probe_video(ffprobe, video)
        full_duration = technical["duration_s"]
        if full_duration <= 0:
            raise SegmentError("视频时长必须大于 0", 2)
        analysis_duration = full_duration
        if args.max_seconds > 0:
            analysis_duration = min(full_duration, args.max_seconds)
        shots_raw, effective_threshold, scene_times = adaptive_shots(
            ffmpeg,
            video,
            analysis_duration,
            args.scene_threshold,
            args.min_shot_seconds,
            args.max_shots,
        )
        if args.extract_clips:
            clips_dir.mkdir(parents=True, exist_ok=True)

        warnings: list[str] = []
        shots: list[dict] = []
        for index, (start, end) in enumerate(shots_raw, start=1):
            shot_id = f"S{index:03d}"
            keyframes = []
            positions = frame_positions(
                start,
                end,
                args.extra_frame_interval,
                args.max_frames_per_shot,
            )
            for frame_index, (role, timestamp) in enumerate(positions, start=1):
                millis = int(round(timestamp * 1000))
                destination = frames_dir / f"{shot_id}_{frame_index:02d}_{role}_{millis:09d}ms.jpg"
                extract_frame(ffmpeg, video, timestamp, destination, args.force)
                keyframes.append({
                    "role": role,
                    "time_s": timestamp,
                    "path": str(destination.resolve()),
                })
            clip_path = None
            if args.extract_clips:
                destination = clips_dir / f"{shot_id}_{int(start * 1000):09d}-{int(end * 1000):09d}ms.mp4"
                warning = extract_clip(ffmpeg, video, start, end, destination, args.force)
                if destination.exists():
                    clip_path = str(destination.resolve())
                if warning:
                    warnings.append(f"{shot_id}: {warning}")
            shots.append({
                "shot_id": shot_id,
                "start_s": start,
                "end_s": end,
                "duration_s": round(end - start, 3),
                "keyframes": keyframes,
                "clip_path": clip_path,
            })

        audio_path = None
        if technical["audio_stream_count"] and not args.no_audio:
            destination = args.output_dir / "audio.wav"
            extract_audio(ffmpeg, video, destination, analysis_duration, args.force)
            audio_path = str(destination.resolve())

        index_path = write_frame_index(args.output_dir, shots)
        manifest = {
            "schema_version": "1.0",
            "source": {
                "video_path": str(video),
                "sha256": sha256_file(video),
                "size_bytes": video.stat().st_size,
            },
            "technical": technical,
            "analysis_window": {
                "start_s": 0.0,
                "end_s": round(analysis_duration, 3),
                "truncated": analysis_duration < full_duration,
            },
            "scene_detection": {
                "requested_threshold": args.scene_threshold,
                "effective_threshold": effective_threshold,
                "min_shot_seconds": args.min_shot_seconds,
                "detected_cut_times_s": scene_times,
            },
            "keyframe_strategy": {
                "base": "start-middle-end",
                "extra_frame_interval_s": args.extra_frame_interval,
                "max_frames_per_shot": args.max_frames_per_shot,
            },
            "shot_count": len(shots),
            "shots": shots,
            "audio_path": audio_path,
            "frame_index_path": str(index_path.resolve()),
            "warnings": warnings,
        }
        manifest_path = args.output_dir / "shot_manifest.json"
        manifest_path.write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
    except SegmentError as exc:
        print(f"错误：{exc}", file=sys.stderr)
        return exc.exit_code
    except OSError as exc:
        print(f"错误：{exc}", file=sys.stderr)
        return 2
    except Exception as exc:
        print(f"错误：{exc}", file=sys.stderr)
        return 1

    print(str(manifest_path.resolve()))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
