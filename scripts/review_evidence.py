#!/usr/bin/env python3
"""Make a focused original-resolution evidence page without a graphics dependency."""
import argparse
import html
import json
from pathlib import Path
import sys
from analysis_contract import file_hash
from frame_evidence import decode_timeline, nearest, extract_batch
from media_tools import resolve_binary


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("video", type=Path)
    p.add_argument("--start", required=True, type=float)
    p.add_argument("--end", required=True, type=float)
    p.add_argument("--every", type=float, default=0.1)
    p.add_argument("--question", required=True)
    p.add_argument("--output-dir", required=True, type=Path)
    args = p.parse_args()
    try:
        if not 0 <= args.start < args.end or args.every <= 0:
            raise ValueError("Invalid range/interval")
        count = int((args.end - args.start) / args.every) + 1
        if count > 120:
            raise ValueError("At most 120 frames per review; narrow range or increase interval")
        if args.output_dir.exists():
            raise ValueError("Use a new output directory")
        ffmpeg, ffprobe = resolve_binary("ffmpeg", "FFMPEG_BIN"), resolve_binary("ffprobe", "FFPROBE_BIN")
        if not ffmpeg or not ffprobe:
            raise ValueError("FFmpeg/FFprobe missing")
        timeline, visual_end = decode_timeline(ffprobe, args.video)
        limit = visual_end if visual_end is not None else timeline[-1]["time_s"]
        if args.end > limit + 0.001:
            raise ValueError("Range beyond decoded video")
        source_hash = file_hash(args.video)
        requested = [min(args.end - 0.000001, args.start + i * args.every) for i in range(count)]
        selected = [nearest(timeline, t, [args.start, args.end]) for t in requested]
        frames = list(extract_batch(ffmpeg, args.video, selected, args.output_dir / "frames").values())
        if file_hash(args.video) != source_hash:
            raise ValueError("Source changed during extraction")
        receipt = {"question": args.question, "range_s": [args.start, args.end], "source_sha256": source_hash, "frames": frames, "reviewed": False, "finding": None, "unresolved": []}
        (args.output_dir / "review.json").write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + "\n")
        cards = []
        for frame in frames:
            relative = Path(frame["path"]).relative_to(args.output_dir.resolve()).as_posix()
            cards.append(f'<figure><a href="{html.escape(relative)}"><img src="{html.escape(relative)}"></a><figcaption>{frame["time_s"]:.6f}s · PTS {frame["pts_s"]:.6f}</figcaption></figure>')
        page = '<!doctype html><meta charset="utf-8"><meta name="viewport" content="width=device-width"><style>body{font:16px system-ui;margin:24px}.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(240px,1fr));gap:16px}figure{margin:0}img{width:100%;height:auto}</style>' + '<h1>' + html.escape(args.question) + '</h1><p>点击查看原尺寸；生成页面尚未代表实际查看。</p><div class="grid">' + ''.join(cards) + '</div>'
        (args.output_dir / "index.html").write_text(page)
        print((args.output_dir / "index.html").resolve())
        return 0
    except (OSError, ValueError, KeyError) as exc:
        print(f"Review extraction failed: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
