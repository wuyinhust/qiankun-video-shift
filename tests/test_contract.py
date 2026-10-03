import copy
import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from analysis_contract import compile_analysis, validate_v2, file_hash, digest
from frame_evidence import nearest
from inspect_analysis import context


def fixture(root):
    source = root / "source.bin"
    clip = root / "clip.bin"
    source.write_bytes(b"synthetic source for contract checks")
    clip.write_bytes(b"synthetic evidence for contract checks")
    sha = file_hash(source)
    return {
        "schema_version": "2.0", "workflow": "prompt", "intent": "faithful", "analysis_status": "complete",
        "source": {"video_path": str(source), "sha256": sha, "duration_s": 4, "analysis_range_s": [0, 4]},
        "shots": [{"id": "S001", "range_s": [0, 4], "end_condition": "ongoing"}],
        "evidence": [{"id": "E1", "kind": "clip", "range_s": [0, 4], "path": str(clip), "sha256": file_hash(clip), "source_sha256": sha}],
        "facts": [
            {"id": "F1", "shot_id": "S001", "kind": "initial", "range_s": [0, 0], "status": "observed", "text": "A red cup sits on the table.", "evidence_ids": ["E1"], "essential": True},
            {"id": "F2", "shot_id": "S001", "kind": "action", "range_s": [0.1, 3.8], "status": "observed", "text": "A hand approaches the cup without touching it.", "evidence_ids": ["E1"], "essential": True},
            {"id": "F3", "shot_id": "S001", "kind": "ending", "range_s": [3.96, 3.96], "status": "observed", "text": "The hand is still approaching when the clip ends.", "evidence_ids": ["E1"], "essential": True}],
        "jobs": [{"id": "J1", "mode": "generic", "source_range_s": [0, 4], "target_range_s": [0, 4], "opening_fact_ids": ["F1"], "closing_fact_ids": ["F3"], "references": []}],
        "audio_plan": {"method": "none", "content_status": "not_requested"}}


class ContractTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.data = fixture(self.root)

    def assertInvalid(self, data):
        with self.assertRaises(ValueError):
            compile_analysis(data)

    def reviewed(self, data):
        compiled = compile_analysis(data)
        compiled["review"] = {"status": "reviewed", "input_digest": digest(compiled), "notes": "Synthetic fixture review declaration for software tests only.", "evidence_ids": ["E1"], "anchors_checked": True, "tail_checked": True}
        return compiled

    def test_complete_packet_and_hashes(self):
        d = self.reviewed(self.data)
        self.assertEqual([], validate_v2(d, self.root, True, True))
        self.assertEqual(["F1", "F2", "F3"], d["derived"]["jobs"][0]["fact_ids"])

    def test_no_automatic_review(self):
        d = compile_analysis(self.data)
        self.assertTrue(validate_v2(d, self.root, False, True))

    def test_derived_new_action_rejected(self):
        d = self.reviewed(self.data)
        d["derived"]["jobs"][0]["prompt"] += " The cup flies away."
        self.assertTrue(validate_v2(d, self.root, False, True))

    def test_changed_fact_invalidates_review(self):
        d = self.reviewed(self.data)
        d["facts"][0]["text"] = "A blue cup sits on the table."
        self.assertEqual("unreviewed", compile_analysis(d)["review"]["status"])

    def test_unchanged_compile_keeps_review(self):
        d = self.reviewed(self.data)
        self.assertEqual(d, compile_analysis(d))

    def test_missing_facts(self):
        d = copy.deepcopy(self.data); d["facts"] = []
        self.assertInvalid(d)

    def test_missing_fact_text(self):
        d = copy.deepcopy(self.data); del d["facts"][0]["text"]
        self.assertInvalid(d)

    def test_coverage_gaps(self):
        for start, end in [(1, 4), (0, 3)]:
            d = copy.deepcopy(self.data); d["shots"][0]["range_s"] = [start, end]
            self.assertInvalid(d)

    def test_source_job_gap(self):
        d = copy.deepcopy(self.data); d["jobs"][0]["source_range_s"] = [1, 4]
        self.assertInvalid(d)

    def test_no_faithful_speed_change(self):
        d = copy.deepcopy(self.data); d["jobs"][0]["target_range_s"] = [0, 2]
        self.assertInvalid(d)

    def test_reference_hash_change(self):
        d = self.reviewed(self.data)
        Path(d["evidence"][0]["path"]).write_bytes(b"changed")
        self.assertTrue(validate_v2(d, self.root, True, True))

    def test_source_hash_change(self):
        d = self.reviewed(self.data)
        Path(d["source"]["video_path"]).write_bytes(b"changed")
        self.assertTrue(validate_v2(d, self.root, True, True))

    def test_wrong_channel(self):
        d = copy.deepcopy(self.data); d["facts"][1]["kind"] = "dialogue"
        self.assertInvalid(d)

    def test_single_frame_cannot_prove_motion(self):
        d = copy.deepcopy(self.data); d["evidence"][0].update(kind="frame", range_s=[0.1, 0.1])
        self.assertInvalid(d)

    def test_wrong_source_evidence(self):
        d = copy.deepcopy(self.data); d["evidence"][0]["source_sha256"] = "0" * 64
        self.assertInvalid(d)

    def test_uncertain_omitted(self):
        d = copy.deepcopy(self.data); d["analysis_status"] = "partial"
        d["facts"][1]["status"] = "uncertain"; d["facts"][1]["essential"] = False
        self.assertNotIn("F2", compile_analysis(d)["derived"]["jobs"][0]["fact_ids"])

    def test_essential_unknown_blocks_final_review(self):
        d = copy.deepcopy(self.data); d["analysis_status"] = "partial"; d["facts"][1]["status"] = "uncertain"
        self.assertTrue(validate_v2(self.reviewed(d), self.root, False, True))

    def test_target_rewrite_preserves_source(self):
        d = copy.deepcopy(self.data); d["intent"] = "adapted"; d["intentional_deviations"] = ["Replace red with blue."]
        d["facts"][0].update(target_text="A blue cup sits on the table.", target_request="User requests blue cup.")
        packet = compile_analysis(d)
        self.assertEqual(self.data["facts"][0]["text"], packet["facts"][0]["text"])
        self.assertEqual("A blue cup sits on the table.", packet["derived"]["jobs"][0]["first_frame_prompt"])

    def test_target_rewrite_requires_intent(self):
        d = copy.deepcopy(self.data); d["facts"][0]["target_text"] = "A blue cup sits on the table."
        self.assertInvalid(d)

    def test_invalid_predecessor(self):
        d = copy.deepcopy(self.data); d["facts"][1]["after"] = ["F3"]
        self.assertInvalid(d)

    def test_job_boundary_does_not_restart_pose(self):
        d = copy.deepcopy(self.data)
        d["jobs"] = [dict(d["jobs"][0], source_range_s=[0, 2], target_range_s=[0, 2]), dict(d["jobs"][0], id="J2", source_range_s=[2, 4], target_range_s=[2, 4])]
        self.assertInvalid(d)

    def test_generic_requires_no_model_capability(self):
        self.assertEqual([], validate_v2(compile_analysis(self.data), self.root))

    def test_h3_capability_required(self):
        d = copy.deepcopy(self.data); d["jobs"][0]["mode"] = "T2VA"
        self.assertInvalid(d)

    def test_h3_supported_duration(self):
        d = copy.deepcopy(self.data); d["jobs"][0]["mode"] = "T2VA"
        d["capability"] = {"min_duration_s": 4, "max_duration_s": 15, "modes": ["T2VA"], "source": "Synthetic platform contract", "checked_at": "2026-10-03"}
        self.assertEqual("T2VA", compile_analysis(d)["derived"]["jobs"][0]["mode"])
        d["capability"]["max_duration_s"] = 3
        self.assertInvalid(d)

    def test_original_audio_once_and_unheard(self):
        d = copy.deepcopy(self.data)
        d["audio_plan"] = {"method": "postproduction_copy", "content_status": "unavailable", "authorized_reuse": True, "stream_index": 1, "start_pts_s": 0.1}
        handoff = compile_analysis(d)["derived"]["audio_handoff"]
        self.assertEqual("once_on_assembled_timeline", handoff["placement"])
        self.assertFalse(handoff["lip_sync_verified"])

    def test_audio_copy_requires_authorization(self):
        d = copy.deepcopy(self.data); d["audio_plan"].update(method="postproduction_copy", stream_index=1, start_pts_s=0)
        self.assertInvalid(d)

    def test_remix_needs_plan(self):
        d = copy.deepcopy(self.data); d["workflow"] = "remix"
        self.assertInvalid(d)

    def test_system_spans_shots_and_event_time_unresolved(self):
        d = copy.deepcopy(self.data); d["workflow"] = "remix"
        d["viral_analysis"] = {"viral_formula": "Question, evidence, reveal."}
        d["replacement_map"] = [{"source_role": "Cup", "target_role": "User product", "affected_system_ids": ["board"]}]
        d["semantic_events"] = [{"id": "price", "source_range_s": [1, 2], "function": "Price reveal", "kind": "phrase", "anchor_id": "target_price_phrase", "target_time_s": None}]
        d["visual_systems"] = [{"id": "board", "role": "Comparison board", "behavior": "Persist and update when price is spoken.", "event_ids": ["price"]}]
        packet = compile_analysis(d)
        self.assertIsNone(packet["derived"]["assembly"]["semantic_events"][0]["target_time_s"])
        d["semantic_events"][0]["target_time_s"] = 1.2
        self.assertInvalid(d)

    def test_pts_selection_respects_shot_boundary(self):
        timeline = [{"decoder_index": i, "pts_s": t + 2, "time_s": t} for i, t in enumerate([0, 0.1, 0.3, 0.8])]
        self.assertEqual(0.3, nearest(timeline, 0.5, [0, 0.8])["time_s"])
        self.assertEqual(0.8, nearest(timeline, 0.8, [0.8, 1])["time_s"])

    def test_last_actual_frame_can_be_far_from_end_at_low_fps(self):
        d = copy.deepcopy(self.data)
        d["source"]["last_frame_time_s"] = 3.5
        d["facts"][-1]["range_s"] = [3.5, 3.5]
        self.assertEqual([], validate_v2(compile_analysis(d), self.root))

    def test_inspection_does_not_return_unrelated_job(self):
        d = compile_analysis(self.data)
        d["jobs"].append(dict(d["jobs"][0], id="unrelated"))
        selected = context(d, job_id="J1")
        self.assertEqual(["J1"], [j["id"] for j in selected["jobs"]])
        self.assertEqual(["E1"], [e["id"] for e in selected["evidence"]])

    def test_all_h3_routes_preserve_same_facts(self):
        for mode in ["T2VA", "I2VA", "FL2VA", "L2VA", "Ref2VA"]:
            with self.subTest(mode=mode):
                d = copy.deepcopy(self.data)
                d["capability"] = {"min_duration_s": 4, "max_duration_s": 15, "modes": [mode], "source": "Synthetic platform contract", "checked_at": "2026-10-03"}
                job = d["jobs"][0]; job["mode"] = mode
                times = {"T2VA": [], "I2VA": [0], "FL2VA": [0, 3.96], "L2VA": [3.96], "Ref2VA": [0]}[mode]
                job["references"] = [{"label": f"<Picture {i + 1}>", "path": d["evidence"][0]["path"], "sha256": d["evidence"][0]["sha256"], "source_time_s": t, "retention": "reference", "description": "Use the reference for the target appearance."} for i, t in enumerate(times)]
                output = compile_analysis(d)["derived"]["jobs"][0]
                self.assertEqual(["F1", "F2", "F3"], output["fact_ids"])
                self.assertEqual("A red cup sits on the table.", output["first_frame_prompt"])
                self.assertEqual("The hand is still approaching when the clip ends.", output["end_frame_prompt"])

    def test_copy_offsets_against_video_origin(self):
        d = copy.deepcopy(self.data)
        d["source"]["time_origin_pts_s"] = 2.0
        d["audio_plan"] = {"method": "postproduction_copy", "content_status": "unavailable", "authorized_reuse": True, "stream_index": 1, "start_pts_s": 2.1}
        self.assertAlmostEqual(0.1, compile_analysis(d)["derived"]["audio_handoff"]["relative_start_s"])

    def test_fact_inspection_returns_only_requested_fact(self):
        d = compile_analysis(self.data)
        d["facts"][2]["after"] = ["F2"]
        selected = context(d, fact_id="F2")
        self.assertEqual(["F2"], [f["id"] for f in selected["facts"]])
        self.assertEqual(["F3"], selected["dependent_fact_ids"])
        self.assertEqual(["F1"], selected["affected_jobs"][0]["opening_fact_ids"])

    def test_shot_inspection_avoids_whole_video_job(self):
        d = compile_analysis(self.data)
        d["shots"].append({"id": "S002", "range_s": [4, 8], "end_condition": "settled"})
        d["facts"].append(dict(d["facts"][0], id="unrelated", shot_id="S002", range_s=[4, 4]))
        selected = context(d, shot_id="S001")
        self.assertEqual(["F1", "F2", "F3"], [f["id"] for f in selected["facts"]])
        self.assertEqual(["S001"], [s["id"] for s in selected["shots"]])

    def test_shot_inspection_includes_incoming_transition(self):
        d = compile_analysis(self.data)
        d["shots"].append({"id": "S002", "range_s": [4, 8], "end_condition": "settled"})
        d["facts"].append(dict(d["facts"][0], id="F4", shot_id="S002", range_s=[4, 4]))
        d["facts"].append(dict(d["facts"][0], id="cut", kind="transition", range_s=[3.96, 4]))
        selected = context(d, shot_id="S002")
        self.assertEqual(["F4"], [f["id"] for f in selected["facts"]])
        self.assertEqual(["cut"], [f["id"] for f in selected["boundary_facts"]])


if __name__ == "__main__":
    unittest.main()
