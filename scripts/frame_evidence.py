"""Decode timestamps once and extract unique frame indices in one FFmpeg pass."""
from bisect import bisect_left
import json
import math
from pathlib import Path
import subprocess
from analysis_contract import file_hash


def decode_timeline(ffprobe, video):
    result = subprocess.run([ffprobe, "-v", "error", "-select_streams", "v:0", "-show_frames", "-show_entries", "frame=best_effort_timestamp_time,duration_time,pkt_duration_time", "-of", "json", str(video)], check=True, capture_output=True, text=True)
    frames = json.loads(result.stdout)["frames"]
    rows = []
    for index, frame in enumerate(frames):
        pts = float(frame["best_effort_timestamp_time"])
        if not math.isfinite(pts) or (rows and pts <= rows[-1]["pts_s"]):
            raise ValueError("Missing/non-increasing PTS; do not substitute average FPS")
        origin = rows[0]["pts_s"] if rows else pts
        rows.append({"decoder_index": index, "pts_s": pts, "time_s": pts - origin})
    if not rows:
        raise ValueError("No decoded frames")
    raw_duration = frames[-1].get("duration_time", frames[-1].get("pkt_duration_time"))
    try:
        duration = float(raw_duration)
        visual_end = rows[-1]["time_s"] + duration if math.isfinite(duration) and duration > 0 else None
    except (ValueError, TypeError):
        visual_end = None
    return rows, visual_end


def nearest(timeline, requested, scope):
    eligible = [r for r in timeline if scope[0] <= r["time_s"] < scope[1]]
    if not eligible:
        raise ValueError("No frame in requested scope")
    times = [r["time_s"] for r in eligible]
    i = bisect_left(times, requested)
    return min((eligible[k] for k in (i - 1, i) if 0 <= k < len(eligible)), key=lambda r: (abs(r["time_s"] - requested), r["time_s"]))


def extract_batch(ffmpeg, video, selected, output_dir):
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    unique = sorted({r["decoder_index"]: r for r in selected}.values(), key=lambda r: r["decoder_index"])
    expression = "+".join(f"eq(n\\,{r['decoder_index']})" for r in unique)
    subprocess.run([ffmpeg, "-v", "error", "-nostdin", "-i", str(video), "-map", "0:v:0", "-vf", f"select={expression}", "-fps_mode", "vfr", "-q:v", "2", "-frames:v", str(len(unique)), "-n", str(output_dir / "evidence-%06d.jpg")], check=True, capture_output=True)
    files = sorted(output_dir.glob("evidence-*.jpg"))
    if len(files) != len(unique):
        raise ValueError("Decoded frame count mismatch")
    return {r["decoder_index"]: {**r, "path": str(p.resolve()), "sha256": file_hash(p), "reviewed": False} for r, p in zip(unique, files)}
