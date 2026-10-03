#!/usr/bin/env python3
"""Read only the affected job or visual system when revising a saved analysis."""
import argparse
import json
from pathlib import Path
from analysis_contract import digest, selected_facts


def context(data, job_id=None, system_id=None):
    result = {"schema_version": data.get("schema_version"), "workflow": data.get("workflow"), "intent": data.get("intent"), "source_sha256": data.get("source", {}).get("sha256"), "review_current": data.get("review", {}).get("status") == "reviewed" and data.get("review", {}).get("input_digest") == digest(data)}
    if job_id:
        job = next((j for j in data.get("jobs", []) if j["id"] == job_id), None)
        if not job:
            raise ValueError("Unknown job")
        facts = selected_facts(data, job)
        ids = {i for f in facts for i in f.get("evidence_ids", [])}
        result.update(jobs=[job], facts=facts, evidence=[e for e in data.get("evidence", []) if e["id"] in ids], accepted_assets=[a for a in data.get("accepted_assets", []) if job_id in a.get("job_ids", [])])
    elif system_id:
        system = next((s for s in data.get("visual_systems", []) if s["id"] == system_id), None)
        if not system:
            raise ValueError("Unknown system")
        result.update(visual_systems=[system], semantic_events=[e for e in data.get("semantic_events", []) if e["id"] in system["event_ids"]], accepted_assets=[a for a in data.get("accepted_assets", []) if system_id in a.get("system_ids", [])])
    else:
        result.update(jobs=[{k: j[k] for k in ("id", "mode", "source_range_s")} for j in data.get("jobs", [])], visual_systems=[{"id": s["id"], "role": s["role"]} for s in data.get("visual_systems", [])], unresolved=[f["id"] for f in data.get("facts", []) if f["status"] == "uncertain"])
    return result


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("analysis", type=Path)
    group = p.add_mutually_exclusive_group()
    group.add_argument("--job")
    group.add_argument("--system")
    args = p.parse_args()
    try:
        result = context(json.loads(args.analysis.read_text()), args.job, args.system)
    except (ValueError, KeyError, TypeError, OSError) as exc:
        p.error(str(exc))
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
