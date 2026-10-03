#!/usr/bin/env python3
"""Read only the affected shot, fact, job or visual system for a local revision."""
import argparse
import json
from pathlib import Path
from analysis_contract import digest, selected_facts


def context(data, job_id=None, system_id=None, shot_id=None, fact_id=None):
    result = {"schema_version": data.get("schema_version"), "workflow": data.get("workflow"), "intent": data.get("intent"), "source_sha256": data.get("source", {}).get("sha256"), "review_current": data.get("review", {}).get("status") == "reviewed" and data.get("review", {}).get("input_digest") == digest(data)}
    if shot_id or fact_id:
        key, value = ("shot_id", shot_id) if shot_id else ("id", fact_id)
        facts = [f for f in data.get("facts", []) if f.get(key) == value]
        if not facts:
            raise ValueError("Unknown or empty shot/fact")
        ids = {f["id"] for f in facts}
        shot_ids = {f["shot_id"] for f in facts}
        boundaries = {t for s in data.get("shots", []) if s["id"] in shot_ids for t in s["range_s"]}
        boundary_facts = [f for f in data.get("facts", []) if f["id"] not in ids and f["kind"] == "transition" and any(abs(t - b) <= 0.12 for t in f["range_s"] for b in boundaries)]
        evidence_ids = {e for f in facts + boundary_facts for e in f.get("evidence_ids", [])}
        jobs = [j for j in data.get("jobs", []) if ids.intersection(f["id"] for f in selected_facts(data, j))]
        result.update(facts=facts, boundary_facts=boundary_facts, evidence=[e for e in data.get("evidence", []) if e["id"] in evidence_ids], affected_jobs=[{k: j[k] for k in ("id", "mode", "source_range_s", "target_range_s", "opening_fact_ids", "closing_fact_ids")} for j in jobs], dependent_fact_ids=[f["id"] for f in data.get("facts", []) if ids.intersection(f.get("after", []))], accepted_assets=[a for a in data.get("accepted_assets", []) if any(j["id"] in a.get("job_ids", []) for j in jobs)])
        if shot_id:
            result["shots"] = [s for s in data.get("shots", []) if s["id"] == shot_id]
    elif job_id:
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
    group.add_argument("--shot")
    group.add_argument("--fact")
    args = p.parse_args()
    try:
        result = context(json.loads(args.analysis.read_text()), args.job, args.system, args.shot, args.fact)
    except (ValueError, KeyError, TypeError, OSError) as exc:
        p.error(str(exc))
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
