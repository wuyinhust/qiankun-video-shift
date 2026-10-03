#!/usr/bin/env python3
"""Reuse a shot manifest as an unreviewed analysis draft, without inventing facts."""
import argparse
import json
from pathlib import Path
from analysis_contract import file_hash


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("manifest", type=Path)
    p.add_argument("--output", required=True, type=Path)
    p.add_argument("--workflow", choices=["prompt", "remix"], default="prompt")
    p.add_argument("--intent", choices=["faithful", "adapted"], default="faithful")
    args = p.parse_args()
    if args.output.exists():
        p.error("Use a new draft path; existing analysis is never overwritten")
    manifest = json.loads(args.manifest.read_text())
    if manifest.get("pipeline_version") != "2.0":
        p.error("Use the v2 media manifest with actual PTS/hash evidence")
    source = manifest["source"]
    if file_hash(source["video_path"]) != source["sha256"]:
        p.error("Source hash changed")
    evidence = []
    seen = {}
    shots = []
    for shot in manifest["shots"]:
        ids = []
        for frame in shot["keyframes"]:
            key = (frame["path"], frame["time_s"])
            if key not in seen:
                if file_hash(frame["path"]) != frame["sha256"]:
                    p.error("Evidence hash changed")
                eid = f"E{len(evidence) + 1:04d}"
                seen[key] = eid
                evidence.append({"id": eid, "kind": "frame", "range_s": [frame["time_s"], frame["time_s"]], "path": frame["path"], "sha256": frame["sha256"], "source_sha256": source["sha256"]})
            ids.append(seen[key])
        shots.append({"id": shot["shot_id"], "range_s": [shot["start_s"], shot["end_s"]], "keyframe_ids": ids, "end_condition": "unknown"})
    scope = [manifest["analysis_window"]["start_s"], manifest["analysis_window"]["end_s"]]
    draft = {"schema_version": "2.0", "workflow": args.workflow, "intent": args.intent, "analysis_status": "partial", "source": {"video_path": source["video_path"], "sha256": source["sha256"], "duration_s": manifest.get("visual_end_s") or manifest["technical"]["duration_s"], "analysis_range_s": scope, "shot_manifest_path": str(args.manifest.resolve())}, "shots": shots, "evidence": evidence, "facts": [], "jobs": [], "audio_plan": {"method": "none", "content_status": "unavailable" if manifest["technical"]["audio_stream_count"] else "no_track"}, "review": {"status": "unreviewed"}}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    draft["source"]["last_frame_time_s"] = max(e["range_s"][0] for e in evidence)
    draft["source"]["time_origin_pts_s"] = manifest["time_origin_pts_s"]
    args.output.write_text(json.dumps(draft, ensure_ascii=False, indent=2) + "\n")
    print(args.output.resolve())


if __name__ == "__main__":
    main()
