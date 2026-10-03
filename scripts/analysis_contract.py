"""Evidence-bound v2 production contract. No model, network or automatic approvals."""
from __future__ import annotations

import copy
import hashlib
import json
import math
from pathlib import Path

VERSION = "2.0"
MODES = {"generic", "T2VA", "I2VA", "FL2VA", "L2VA", "Ref2VA"}
KINDS = {"identity", "initial", "state", "action", "camera", "ending", "transition", "dialogue", "soundscape", "music"}


def number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def span(value):
    return isinstance(value, list) and len(value) == 2 and all(number(v) for v in value) and 0 <= value[0] <= value[1]


def text(value):
    return isinstance(value, str) and bool(value.strip()) and not any(t in value for t in ("REQUIRED_", "同上", "...", "…"))


def file_hash(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def digest(data):
    inputs = {k: v for k, v in data.items() if k not in {"derived", "compilation", "review"}}
    return hashlib.sha256(json.dumps(inputs, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()).hexdigest()


def rows(data, key, errors):
    value = data.get(key, [])
    if not isinstance(value, list) or any(not isinstance(x, dict) for x in value):
        errors.append(f"{key}: expected array of objects")
        return {}
    indexed = {}
    for row in value:
        rid = row.get("id")
        if not isinstance(rid, str) or not rid or rid in indexed:
            errors.append(f"{key}: missing/duplicate id")
        else:
            indexed[rid] = row
    return indexed


def inside(inner, outer, tolerance=0.0001):
    return span(inner) and span(outer) and outer[0] - tolerance <= inner[0] <= inner[1] <= outer[1] + tolerance


def coverage(ranges, scope, errors, label):
    if not span(scope) or not ranges:
        errors.append(f"{label}: missing coverage")
        return
    cursor = scope[0]
    for r in ranges:
        if not span(r) or r[0] >= r[1]:
            errors.append(f"{label}: invalid range")
            continue
        if abs(r[0] - cursor) > 0.001:
            errors.append(f"{label}: gap/overlap at {cursor}")
        cursor = r[1]
    if abs(cursor - scope[1]) > 0.001:
        errors.append(f"{label}: incomplete tail")


def validate_inputs(data):
    errors = []
    if data.get("schema_version") != "2.0":
        return ["schema_version must be 2.0"]
    if data.get("workflow") not in {"prompt", "remix"}:
        errors.append("workflow must be prompt/remix")
    if data.get("intent") not in {"faithful", "adapted"}:
        errors.append("intent must be faithful/adapted")
    if data.get("analysis_status") not in {"complete", "partial"}:
        errors.append("analysis_status must be complete/partial")
    source = data.get("source", {})
    source = source if isinstance(source, dict) else {}
    duration = source.get("duration_s")
    scope = source.get("analysis_range_s")
    if not number(duration) or duration <= 0 or not inside(scope, [0, duration]):
        errors.append("source: invalid duration/analysis_range_s")
    sha = source.get("sha256")
    if not isinstance(sha, str) or len(sha) != 64 or any(c not in "0123456789abcdef" for c in sha):
        errors.append("source: sha256 required")
    if not isinstance(source.get("video_path"), str):
        errors.append("source: video_path required")
    shots = rows(data, "shots", errors)
    evidence = rows(data, "evidence", errors)
    facts = rows(data, "facts", errors)
    jobs = rows(data, "jobs", errors)
    if not facts or not jobs:
        errors.append("facts/jobs must be nonempty")
    coverage([s.get("range_s") for s in shots.values()], scope, errors, "shots")
    for sid, shot in shots.items():
        if shot.get("end_condition") not in {"settled", "ongoing", "cutoff", "unknown"}:
            errors.append(f"{sid}: end_condition required")
    for eid, ev in evidence.items():
        r = ev.get("range_s")
        kind = ev.get("kind")
        if kind not in {"frame", "clip", "audio"} or not inside(r, scope):
            errors.append(f"{eid}: invalid evidence channel/range")
        if kind == "frame" and span(r) and (r[0] != r[1] or not number(duration) or r[0] >= duration):
            errors.append(f"{eid}: frame needs one actual time before video end")
        if kind in {"clip", "audio"} and span(r) and r[0] >= r[1]:
            errors.append(f"{eid}: empty temporal evidence")
        if ev.get("source_sha256") != sha:
            errors.append(f"{eid}: evidence source hash mismatch")
        if not isinstance(ev.get("path"), str) or not isinstance(ev.get("sha256"), str) or len(ev["sha256"]) != 64:
            errors.append(f"{eid}: path/hash required")
    for fid, fact in facts.items():
        shot = shots.get(fact.get("shot_id"), {})
        r = fact.get("range_s")
        status, kind = fact.get("status"), fact.get("kind")
        if kind not in KINDS or not inside(r, shot.get("range_s")) or not text(fact.get("text")):
            errors.append(f"{fid}: invalid kind, shot range or text")
        if status not in {"observed", "uncertain", "user_requested"}:
            errors.append(f"{fid}: invalid fact status")
        if status == "uncertain" and data.get("analysis_status") != "partial":
            errors.append(f"{fid}: uncertain fact needs partial analysis")
        if status == "user_requested" and (data.get("intent") != "adapted" or not text(fact.get("request"))):
            errors.append(f"{fid}: requested additions need adapted intent and request")
        if "target_text" in fact and (data.get("intent") != "adapted" or not text(fact.get("target_text")) or not text(fact.get("target_request"))):
            errors.append(f"{fid}: target rewrite needs adapted intent, text and request")
        if fact.get("omit") and (data.get("intent") != "adapted" or not text(fact.get("target_request"))):
            errors.append(f"{fid}: omission needs explicit adaptation request")
        ids = fact.get("evidence_ids", [])
        if not isinstance(ids, list) or any(i not in evidence for i in ids):
            errors.append(f"{fid}: unknown evidence")
            ids = []
        evs = [evidence[i] for i in ids]
        if status == "observed":
            audio = kind in {"dialogue", "soundscape", "music"}
            usable = [e for e in evs if (e.get("kind") == "audio") == audio and inside(e.get("range_s"), shot.get("range_s"))]
            if not usable:
                errors.append(f"{fid}: missing matching evidence channel")
            if kind in {"action", "camera", "transition"}:
                frames = {e["range_s"][0] for e in usable if e.get("kind") == "frame" and span(e.get("range_s")) and inside(e["range_s"], r)}
                clips = [e for e in usable if e.get("kind") == "clip" and inside(r, e.get("range_s"))]
                if len(frames) < 2 and not clips:
                    errors.append(f"{fid}: motion needs distinct frame times or covering clip")
            elif usable and not any(inside(e.get("range_s"), r) or inside(r, e.get("range_s")) for e in usable):
                errors.append(f"{fid}: evidence not at fact time")
        after = fact.get("after", [])
        if not isinstance(after, list):
            errors.append(f"{fid}: after must be an array")
        else:
            for prior in after:
                predecessor = facts.get(prior)
                if not predecessor or prior == fid or not span(r) or not span(predecessor.get("range_s")) or predecessor["range_s"][1] > r[0]:
                    errors.append(f"{fid}: invalid predecessor {prior}")
    deviations = data.get("intentional_deviations", [])
    if data.get("intent") == "adapted" and (not isinstance(deviations, list) or not deviations or not all(text(v) for v in deviations)):
        errors.append("adapted intent needs intentional_deviations")
    capability = data.get("capability", {})
    capability = capability if isinstance(capability, dict) else {}
    for jid, job in jobs.items():
        r, target = job.get("source_range_s"), job.get("target_range_s")
        mode = job.get("mode")
        if mode not in MODES or not inside(r, scope) or not span(target) or target[0] >= target[1]:
            errors.append(f"{jid}: invalid mode or source/target range")
            continue
        if r[0] >= r[1]:
            errors.append(f"{jid}: empty source range")
        length = target[1] - target[0]
        if data.get("intent") == "faithful" and abs(length - (r[1] - r[0])) > 0.001:
            errors.append(f"{jid}: faithful duration changed")
        if mode != "generic":
            if not number(capability.get("max_duration_s")) or not number(capability.get("min_duration_s")) or not isinstance(capability.get("modes"), list) or not text(capability.get("source")) or not text(capability.get("checked_at")):
                errors.append(f"{jid}: verified platform capability required")
            elif not capability["min_duration_s"] <= length <= capability["max_duration_s"] or mode not in capability["modes"]:
                errors.append(f"{jid}: unsupported duration/mode")
        for key in ("opening_fact_ids", "closing_fact_ids"):
            ids = job.get(key, [])
            if not isinstance(ids, list) or not ids or any(i not in facts or facts[i].get("status") == "uncertain" for i in ids):
                errors.append(f"{jid}: valid {key} required")
                continue
            boundary = r[0] if key.startswith("opening") else r[1]
            for i in ids:
                f = facts[i]
                fr = f.get("range_s")
                if f.get("kind") not in {"identity", "initial", "state", "ending"} or not inside(fr, r) or not span(fr) or min(abs(v - boundary) for v in fr) > 0.12:
                    errors.append(f"{jid}: {key} not bound to current boundary")
        crossed = [s for s in shots.values() if span(s.get("range_s")) and s["range_s"][0] < r[1] and s["range_s"][1] > r[0]]
        if mode in {"I2VA", "FL2VA", "L2VA"} and len(crossed) != 1:
            errors.append(f"{jid}: keyframe job must stay in one source shot")
        for fid, f in facts.items():
            fr = f.get("range_s")
            if f.get("status") != "uncertain" and f.get("kind") in {"action", "transition"} and span(fr) and fr[0] < r[1] and fr[1] > r[0] and not inside(fr, r):
                errors.append(f"{jid}/{fid}: split cross-job action at its actual state")
        refs = job.get("references", [])
        if not isinstance(refs, list) or any(not isinstance(v, dict) for v in refs):
            errors.append(f"{jid}: references must be objects")
            refs = []
        expected = {"I2VA": 1, "FL2VA": 2, "L2VA": 1, "T2VA": 0}.get(mode)
        if expected is not None and len(refs) != expected:
            errors.append(f"{jid}: wrong reference count")
        labels = []
        for ref in refs:
            label = ref.get("label", "")
            labels.append(label)
            if not isinstance(label, str) or not label.startswith(("<Picture ", "<Video ", "<Audio ", "<Subject ")) or not label.endswith(">"):
                errors.append(f"{jid}: invalid reference label")
            if not isinstance(ref.get("path"), str) or not isinstance(ref.get("sha256"), str) or len(ref["sha256"]) != 64:
                errors.append(f"{jid}: actual reference file/hash required")
            if mode == "Ref2VA" and (ref.get("retention") not in {"fully_copy", "partially_copy", "reference"} or not text(ref.get("description"))):
                errors.append(f"{jid}: explicit reference relation required")
        if len(labels) != len(set(labels)) or (mode == "Ref2VA" and not refs):
            errors.append(f"{jid}: missing/duplicate references")
        if mode in {"I2VA", "FL2VA", "L2VA"}:
            if labels != [f"<Picture {i + 1}>" for i in range(len(refs))]:
                errors.append(f"{jid}: local Picture numbering required")
            for ref, boundary in zip(refs, ([r[1]] if mode == "L2VA" else [r[0], r[1]])):
                if not number(ref.get("source_time_s")) or abs(ref["source_time_s"] - boundary) > 0.12:
                    errors.append(f"{jid}: reference not aligned to current boundary")
    if data.get("intent") == "faithful":
        coverage([j.get("source_range_s") for j in jobs.values()], scope, errors, "jobs source")
    if jobs:
        targets = [j.get("target_range_s") for j in jobs.values()]
        last = targets[-1]
        coverage(targets, [0, last[1]] if span(last) else None, errors, "jobs target")
    audio = data.get("audio_plan", {})
    audio = audio if isinstance(audio, dict) else {}
    if audio.get("method") not in {"none", "postproduction_copy", "reference", "recreate"}:
        errors.append("audio_plan method required")
    if audio.get("content_status") not in {"verified", "unavailable", "no_track", "not_requested"}:
        errors.append("audio_plan content_status required")
    if audio.get("method") == "postproduction_copy":
        if data.get("intent") != "faithful" or not audio.get("authorized_reuse") or not number(audio.get("stream_index")) or not number(audio.get("start_pts_s")):
            errors.append("audio copy needs faithful mapping, authorized reuse and stream metadata")
    if audio.get("content_status") != "verified" and any(f.get("status") == "observed" and f.get("kind") in {"dialogue", "soundscape", "music"} for f in facts.values()):
        errors.append("unheard audio cannot become observed sound facts")
    events = rows(data, "semantic_events", errors)
    systems = rows(data, "visual_systems", errors)
    for eid, ev in events.items():
        if not inside(ev.get("source_range_s"), scope) or not text(ev.get("function")) or not text(ev.get("anchor_id")) or ev.get("kind") not in {"phrase", "action", "clock"}:
            errors.append(f"{eid}: semantic event needs source, function and target anchor")
        resolved = ev.get("target_time_s")
        if resolved is not None and (not number(resolved) or resolved < 0 or not text(ev.get("timing_source"))):
            errors.append(f"{eid}: resolved time needs actual timing source")
    for sid, system in systems.items():
        if not text(system.get("role")) or not text(system.get("behavior")) or not isinstance(system.get("event_ids"), list) or any(i not in events for i in system.get("event_ids", [])):
            errors.append(f"{sid}: visual system needs role/behavior/event references")
    if data.get("workflow") == "remix" and (not isinstance(data.get("viral_analysis"), dict) or not text(data.get("viral_analysis", {}).get("viral_formula")) or not isinstance(data.get("replacement_map"), list) or not data.get("replacement_map")):
        errors.append("remix needs viral formula and replacement_map")
    return errors


def selected_facts(data, job):
    r = job["source_range_s"]
    return [f for f in data["facts"] if f["status"] != "uncertain" and not f.get("omit") and inside(f["range_s"], r)]


def output_text(fact):
    return fact.get("target_text", fact["text"])


def render(data):
    outputs = []
    facts = {f["id"]: f for f in data["facts"]}
    for job in data["jobs"]:
        selected = selected_facts(data, job)
        start, end = job["source_range_s"]
        length = job["target_range_s"][1] - job["target_range_s"][0]
        scale = length / (end - start)
        main = []
        for shot in data["shots"]:
            fs = [f for f in selected if f["shot_id"] == shot["id"] and f["kind"] not in {"soundscape", "music"}]
            if not fs:
                continue
            n = len(main) + 1
            at = max(0, (shot["range_s"][0] - start) * scale)
            prefix = f"[Shot {n}] " + (f"At 00:{at:06.3f}, " if n > 1 else "")
            sentences = []
            for f in sorted(fs, key=lambda f: f["range_s"]):
                timing = ""
                if f["kind"] in {"action", "camera", "dialogue"}:
                    a, b = [(v - start) * scale for v in f["range_s"]]
                    timing = f"From {a:.3f} to {b:.3f} seconds, "
                sentences.append(timing + output_text(f))
            main.append(prefix + " ".join(sentences))
        description = " ".join(main)
        sound = " ".join(output_text(f) for f in selected if f["kind"] == "soundscape") or "N/A"
        music = " ".join(output_text(f) for f in selected if f["kind"] == "music") or "N/A"
        mode = job["mode"]
        alignment = ""
        if mode == "I2VA":
            alignment = "For the target video, at 0.00 seconds into the target video, <Picture 1> (from [Shot 1]) is fully referenced.\n\n"
        elif mode == "FL2VA":
            alignment = f"How the reference pictures align with the target video — Picture 1 (from Shot 1) aligns with the 0.00-second mark of the target video; Picture 2 (from Shot 1) aligns with the {length:.2f}-second mark of the target video.\n\n"
        elif mode == "L2VA":
            alignment = f"How the reference pictures align with the target video — <Picture 1> (from [Shot 1]) aligns with the {length:.2f}-second mark of the target video.\n\n"
        if mode == "Ref2VA":
            definitions = "\n".join(r["label"] + " " + r["description"] for r in job["references"])
            retention = "\n".join(r["label"] + ": " + r["retention"] + " - " + r["description"] for r in job["references"])
            prompt = f"subject_definitions: {definitions}\n\nsummary: Reconstruct the specified timeline using the declared reference relationships.\n\nretention_analysis: {retention}\n\ndetailed_description: {description}\n\noverall_soundscape: {sound}\n\nnon_diegetic_music: {music}"
        elif mode == "generic":
            prompt = description + (f"\nSoundscape: {sound}" if sound != "N/A" else "") + (f"\nMusic: {music}" if music != "N/A" else "")
        else:
            prompt = alignment + f"integrated_multimodal_description: {description}\n\noverall_soundscape: {sound}\n\nnon_diegetic_music: {music}"
        opening = " ".join(output_text(facts[i]) for i in job["opening_fact_ids"])
        closing = " ".join(output_text(facts[i]) for i in job["closing_fact_ids"])
        motion = " ".join(output_text(f) for f in selected if f["kind"] in {"action", "camera", "transition", "ending"})
        outputs.append({"id": job["id"], "mode": mode, "source_range_s": job["source_range_s"], "target_range_s": job["target_range_s"], "fact_ids": [f["id"] for f in selected], "first_frame_prompt": opening, "motion_prompt": motion, "end_frame_prompt": closing, "prompt": prompt})
    result = {"jobs": outputs, "assembly": {"semantic_events": data.get("semantic_events", []), "visual_systems": data.get("visual_systems", [])}}
    if data["audio_plan"]["method"] == "postproduction_copy":
        result["audio_handoff"] = {"source_path": data["source"]["video_path"], "source_sha256": data["source"]["sha256"], "stream_index": data["audio_plan"]["stream_index"], "start_pts_s": data["audio_plan"]["start_pts_s"], "placement": "once_on_assembled_timeline", "remove_generated_audio": True, "maps": [{"source": j["source_range_s"], "target": j["target_range_s"]} for j in data["jobs"]], "lip_sync_verified": False}
    return result


def compile_analysis(data):
    errors = validate_inputs(data)
    if errors:
        raise ValueError("\n".join(errors))
    result = copy.deepcopy(data)
    current = digest(result)
    result["derived"] = render(result)
    result["compilation"] = {"version": VERSION, "input_digest": current}
    if result.get("review", {}).get("input_digest") != current:
        result["review"] = {"status": "unreviewed", "input_digest": current}
    return result


def validate_v2(data, base_dir, check_files=False, require_reviewed=False):
    errors = validate_inputs(data)
    if errors:
        return errors
    current = digest(data)
    if data.get("compilation") != {"version": VERSION, "input_digest": current} or data.get("derived") != render(data):
        errors.append("stale/edited derived output: recompile from facts")
    review = data.get("review", {})
    if not isinstance(review, dict):
        errors.append("review must be an object")
        review = {}
    if require_reviewed or review.get("status") == "reviewed":
        if review.get("status") != "reviewed" or review.get("input_digest") != current or not text(review.get("notes")):
            errors.append("current semantic/media review required")
        required_ids = {i for f in data["facts"] if f["status"] == "observed" for i in f.get("evidence_ids", [])}
        if not required_ids.issubset(set(review.get("evidence_ids", []))) or review.get("anchors_checked") is not True or review.get("tail_checked") is not True:
            errors.append("review must cover used evidence, essential anchors and tail")
        if any(f.get("essential") and f["status"] == "uncertain" for f in data["facts"]):
            errors.append("unresolved essential fact: draft only")
        delivered = {i for j in data["derived"]["jobs"] for i in j["fact_ids"]}
        if any(f.get("essential") and f["id"] not in delivered for f in data["facts"]):
            errors.append("essential fact missing from delivery")
    if check_files:
        assets = [dict(path=data["source"]["video_path"], sha256=data["source"]["sha256"])] + data["evidence"] + [r for j in data["jobs"] for r in j.get("references", [])]
        checked = set()
        for asset in assets:
            path = Path(asset["path"]).expanduser()
            if not path.is_absolute():
                path = Path(base_dir) / path
            key = (str(path), asset["sha256"])
            if key in checked:
                continue
            checked.add(key)
            try:
                if file_hash(path) != asset["sha256"]:
                    errors.append(f"asset hash mismatch: {asset['path']}")
            except OSError:
                errors.append(f"asset missing: {asset['path']}")
    return errors
