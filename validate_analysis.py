#!/usr/bin/env python3
"""Validate the cross-stage analysis contract and MiniMax H3 output invariants."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import sys


MOMENT_TYPES = {
    "hook", "curiosity_gap", "pain_point", "relatability",
    "authority", "social_proof", "super_effect", "transformation",
    "twist", "urgency", "value", "cta",
}
H3_MODES = {"T2VA", "I2VA", "FL2VA", "L2VA", "Ref2VA"}
BASE_FIELDS = [
    "integrated_multimodal_description:",
    "overall_soundscape:",
    "non_diegetic_music:",
]
REF_FIELDS = [
    "subject_definitions:",
    "summary:",
    "retention_analysis:",
    "detailed_description:",
    "overall_soundscape:",
    "non_diegetic_music:",
]
H3_REFERENCE_RE = re.compile(r"^<(?:Subject|Picture|Video|Audio) [1-9][0-9]*>$")


def is_number(value) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def check_score(errors: list[str], label: str, value) -> None:
    if not is_number(value) or not 0 <= float(value) <= 10:
        errors.append(f"{label} 必须是 0–10 的数字")


def check_complete_text(errors: list[str], label: str, value) -> bool:
    if not isinstance(value, str) or not value.strip():
        errors.append(f"{label} 必须是完整字符串")
        return False
    if "..." in value or "…" in value or "同上" in value or "REQUIRED_" in value:
        errors.append(f"{label} 含省略或模板占位符")
        return False
    return True


def check_field_order(errors: list[str], label: str, prompt: str, fields: list[str]) -> None:
    positions = [prompt.find(field) for field in fields]
    missing = [field for field, position in zip(fields, positions) if position < 0]
    if missing:
        errors.append(f"{label} 缺少字段：{', '.join(missing)}")
        return
    if positions != sorted(positions):
        errors.append(f"{label} 字段顺序不符合官方契约")


def validate(data: dict, check_files: bool, require_h3: bool) -> list[str]:
    errors: list[str] = []
    if data.get("schema_version") != "1.0":
        errors.append("schema_version 必须为 1.0")
    for key in ["source", "shots", "viral_analysis", "reconstruction"]:
        if key not in data:
            errors.append(f"缺少顶层字段：{key}")

    source = data.get("source") if isinstance(data.get("source"), dict) else {}
    duration = source.get("duration_s")
    if not is_number(duration) or duration <= 0:
        errors.append("source.duration_s 必须是正数")
        duration = None
    for key in ["manifest_path", "video_path"]:
        value = source.get(key)
        if not isinstance(value, str) or not value.strip():
            errors.append(f"source.{key} 必须是文件路径")
        elif check_files and not Path(value).is_file():
            errors.append(f"source.{key} 文件不存在：{value}")

    shots = data.get("shots")
    if not isinstance(shots, list) or not shots:
        errors.append("shots 必须是非空数组")
        shots = []
    shot_ids: set[str] = set()
    previous_start = -1.0
    previous_end = -1.0
    for index, shot in enumerate(shots):
        label = f"shots[{index}]"
        if not isinstance(shot, dict):
            errors.append(f"{label} 必须是对象")
            continue
        shot_id = shot.get("shot_id")
        if not isinstance(shot_id, str) or not shot_id:
            errors.append(f"{label}.shot_id 缺失")
        elif not re.fullmatch(r"S[0-9]{3}", shot_id):
            errors.append(f"{label}.shot_id 必须使用 S001 形式：{shot_id}")
        elif shot_id in shot_ids:
            errors.append(f"{label}.shot_id 重复：{shot_id}")
        else:
            shot_ids.add(shot_id)
        start = shot.get("start_s")
        end = shot.get("end_s")
        if not is_number(start) or not is_number(end) or float(start) >= float(end):
            errors.append(f"{label} 时间范围无效")
        else:
            if float(start) < previous_start:
                errors.append(f"{label} 未按时间排序")
            if previous_end >= 0 and float(start) < previous_end - 0.05:
                errors.append(f"{label} 与上一镜头重叠")
            previous_start = float(start)
            previous_end = max(previous_end, float(end))
            if duration is not None and float(end) > float(duration) + 0.05:
                errors.append(f"{label}.end_s 超出源视频时长")
        keyframes = shot.get("keyframes")
        if not isinstance(keyframes, list) or not keyframes:
            errors.append(f"{label}.keyframes 必须至少有一张")
        else:
            for frame_index, frame in enumerate(keyframes):
                path = frame.get("path") if isinstance(frame, dict) else frame
                frame_label = f"{label}.keyframes[{frame_index}]"
                if not isinstance(path, str) or not path.strip():
                    errors.append(f"{frame_label}.path 缺失")
                elif check_files and not Path(path).is_file():
                    errors.append(f"{label}.keyframes[{frame_index}] 文件不存在：{path}")
                if isinstance(frame, dict) and frame.get("time_s") is not None:
                    timestamp = frame.get("time_s")
                    if not is_number(timestamp):
                        errors.append(f"{frame_label}.time_s 必须是数字")
                    elif is_number(start) and is_number(end) and not (
                        float(start) - 0.05 <= float(timestamp) <= float(end) + 0.05
                    ):
                        errors.append(f"{frame_label}.time_s 不在镜头范围内")

    viral = data.get("viral_analysis") if isinstance(data.get("viral_analysis"), dict) else {}
    if viral.get("score_kind") not in {"structural_potential", "observed_performance"}:
        errors.append("viral_analysis.score_kind 必须是 structural_potential 或 observed_performance")
    check_score(errors, "viral_analysis.overall_score", viral.get("overall_score"))
    check_score(errors, "viral_analysis.hook_strength", viral.get("hook_strength"))
    for key in ["narrative_structure", "core_appeal", "target_audience", "viral_formula"]:
        check_complete_text(errors, f"viral_analysis.{key}", viral.get(key))
    for key in ["replicable_patterns", "potential_concerns"]:
        values = viral.get(key)
        if not isinstance(values, list) or not values:
            errors.append(f"viral_analysis.{key} 必须是非空数组")
        else:
            for index, value in enumerate(values):
                check_complete_text(errors, f"viral_analysis.{key}[{index}]", value)
    moments = viral.get("key_moments")
    if not isinstance(moments, list):
        errors.append("viral_analysis.key_moments 必须是数组")
        moments = []
    elif not moments:
        errors.append("viral_analysis.key_moments 必须至少有一项")
    previous_moment = -1.0
    for index, moment in enumerate(moments):
        label = f"viral_analysis.key_moments[{index}]"
        if not isinstance(moment, dict):
            errors.append(f"{label} 必须是对象")
            continue
        primary = moment.get("primary_type")
        secondary = moment.get("secondary_type")
        if primary not in MOMENT_TYPES:
            errors.append(f"{label}.primary_type 非法：{primary}")
        if secondary not in (None, "") and secondary not in MOMENT_TYPES:
            errors.append(f"{label}.secondary_type 非法：{secondary}")
        start = moment.get("start_s")
        end = moment.get("end_s")
        if not is_number(start) or not is_number(end) or float(start) >= float(end):
            errors.append(f"{label} 时间范围无效")
        else:
            if float(start) < previous_moment:
                errors.append(f"{label} 未按时间排序")
            previous_moment = float(start)
            if duration is not None and float(end) > float(duration) + 0.05:
                errors.append(f"{label}.end_s 超出源视频时长")
        check_score(errors, f"{label}.score", moment.get("score"))
        for text_key in ["title", "description", "mechanism"]:
            check_complete_text(errors, f"{label}.{text_key}", moment.get(text_key))
        evidence = moment.get("evidence_shots")
        if not isinstance(evidence, list) or not evidence:
            errors.append(f"{label}.evidence_shots 必须非空")
        else:
            unknown = [item for item in evidence if item not in shot_ids]
            if unknown:
                errors.append(f"{label} 引用了不存在的镜头：{unknown}")

    reconstruction = data.get("reconstruction") if isinstance(data.get("reconstruction"), dict) else {}
    for key in ["generic_faithful_prompt", "generic_enhanced_prompt"]:
        check_complete_text(errors, f"reconstruction.{key}", reconstruction.get(key))
    variants = reconstruction.get("variants")
    if not isinstance(variants, list):
        errors.append("reconstruction.variants 必须是数组")
    else:
        if len(variants) != 3:
            errors.append("reconstruction.variants 必须恰好包含三个变式")
        dimensions = {item.get("dimension") for item in variants if isinstance(item, dict)}
        expected = {"composition", "lighting", "style"}
        if dimensions != expected:
            errors.append(f"reconstruction.variants 维度必须恰好为 {sorted(expected)}")
        for index, item in enumerate(variants):
            if not isinstance(item, dict):
                errors.append(f"reconstruction.variants[{index}] 必须是对象")
                continue
            check_complete_text(
                errors,
                f"reconstruction.variants[{index}].prompt",
                item.get("prompt"),
            )

    consistency = reconstruction.get("consistency")
    if not isinstance(consistency, dict):
        errors.append("reconstruction.consistency 必须是对象")
    else:
        for key in ["original_lock", "style_lock"]:
            check_complete_text(errors, f"reconstruction.consistency.{key}", consistency.get(key))
    for key in ["negative_constraints", "originality_changes"]:
        values = reconstruction.get(key)
        if not isinstance(values, list) or not values:
            errors.append(f"reconstruction.{key} 必须是非空数组")
        else:
            for index, value in enumerate(values):
                check_complete_text(errors, f"reconstruction.{key}[{index}]", value)

    model_outputs = data.get("model_outputs")
    h3_outputs = model_outputs.get("h3") if isinstance(model_outputs, dict) else None
    if require_h3 and (not isinstance(h3_outputs, list) or not h3_outputs):
        errors.append("要求 H3 输出，但 model_outputs.h3 为空")
    if isinstance(h3_outputs, list):
        segment_ids: set[str] = set()
        for index, item in enumerate(h3_outputs):
            label = f"model_outputs.h3[{index}]"
            if not isinstance(item, dict):
                errors.append(f"{label} 必须是对象")
                continue
            mode = item.get("mode")
            if mode not in H3_MODES:
                errors.append(f"{label}.mode 非法：{mode}")
            segment_id = item.get("segment_id")
            if not isinstance(segment_id, str) or not segment_id.strip():
                errors.append(f"{label}.segment_id 缺失")
            elif segment_id in segment_ids:
                errors.append(f"{label}.segment_id 重复：{segment_id}")
            else:
                segment_ids.add(segment_id)
            source_start = item.get("source_start_s")
            source_end = item.get("source_end_s")
            if (
                not is_number(source_start)
                or not is_number(source_end)
                or float(source_start) >= float(source_end)
            ):
                errors.append(f"{label} 源时间范围无效")
            elif duration is not None and float(source_end) > float(duration) + 0.05:
                errors.append(f"{label}.source_end_s 超出源视频时长")
            target_duration = item.get("target_duration_s")
            if not is_number(target_duration) or not 4 <= float(target_duration) <= 15:
                errors.append(f"{label}.target_duration_s 必须位于 4–15 秒")
            references = item.get("references")
            if not isinstance(references, list):
                errors.append(f"{label}.references 必须是数组")
                references = []
            for ref_index, reference in enumerate(references):
                if not isinstance(reference, str) or not H3_REFERENCE_RE.fullmatch(reference):
                    errors.append(f"{label}.references[{ref_index}] 标签非法：{reference}")
            if mode == "T2VA" and references:
                errors.append(f"{label}.mode=T2VA 时不应包含参考素材")
            if mode in H3_MODES - {"T2VA"} and not references:
                errors.append(f"{label}.mode={mode} 时必须列出参考素材")
            prompt = item.get("prompt")
            if not check_complete_text(errors, f"{label}.prompt", prompt):
                continue
            check_field_order(
                errors,
                label,
                prompt,
                REF_FIELDS if mode == "Ref2VA" else BASE_FIELDS,
            )
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate viral-video analysis.json")
    parser.add_argument("analysis", type=Path)
    parser.add_argument("--check-files", action="store_true")
    parser.add_argument("--require-h3", action="store_true")
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args()
    try:
        data = json.loads(args.analysis.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        print(f"错误：无法读取分析文件：{exc}", file=sys.stderr)
        return 2
    if not isinstance(data, dict):
        print("错误：analysis 顶层必须是对象", file=sys.stderr)
        return 2
    errors = validate(data, args.check_files, args.require_h3)
    if errors:
        for error in errors:
            print(f"- {error}", file=sys.stderr)
        return 2
    if not args.quiet:
        print("analysis.json validation passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
