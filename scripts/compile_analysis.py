#!/usr/bin/env python3
"""Compile declared facts into one reproducible prompt/assembly packet."""
import argparse
import json
from pathlib import Path
import sys
from analysis_contract import compile_analysis


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("analysis", type=Path)
    parser.add_argument("--output", type=Path, help="defaults to input; relative assets stay anchored to input")
    args = parser.parse_args()
    try:
        data = json.loads(args.analysis.read_text())
        target = args.output or args.analysis
        if target.resolve().parent != args.analysis.resolve().parent:
            for asset in data.get("evidence", []) + [r for j in data.get("jobs", []) for r in j.get("references", [])]:
                p = Path(asset["path"])
                if not p.is_absolute():
                    asset["path"] = str((args.analysis.resolve().parent / p).resolve())
            p = Path(data["source"]["video_path"])
            if not p.is_absolute():
                data["source"]["video_path"] = str((args.analysis.resolve().parent / p).resolve())
        compiled = compile_analysis(data)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(compiled, ensure_ascii=False, indent=2) + "\n")
    except (OSError, ValueError, KeyError, TypeError) as exc:
        print(f"Compilation failed: {exc}", file=sys.stderr)
        return 2
    print(str(target.resolve()))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
