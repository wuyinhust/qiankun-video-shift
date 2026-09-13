# 统一输出契约

`analysis.json` 是四式共用的事实源。字段可以扩展，但以下必需结构不得改名。

```json
{
  "schema_version": "1.0",
  "source": {
    "manifest_path": "/abs/source_manifest.json",
    "video_path": "/abs/video.mp4",
    "sha256": "REQUIRED_SOURCE_SHA256",
    "duration_s": 30.0,
    "aspect_ratio": "9:16"
  },
  "shots": [
    {
      "shot_id": "S001",
      "start_s": 0.0,
      "end_s": 2.4,
      "keyframes": ["/abs/frame1.jpg", "/abs/frame2.jpg"],
      "observation": "客观画面事实",
      "shot_size": "close-up",
      "camera_angle": "eye-level",
      "composition": "REQUIRED_OBJECTIVE_COMPOSITION",
      "subject_motion": "REQUIRED_SUBJECT_MOTION",
      "camera_motion": "REQUIRED_CAMERA_MOTION",
      "lighting_color": "REQUIRED_LIGHTING_AND_COLOR",
      "visible_text": "REQUIRED_VISIBLE_TEXT_OR_NONE",
      "audio": "REQUIRED_AUDIO_OBSERVATION_OR_NONE",
      "transition": "hard cut",
      "uncertainty": [],
      "boundary_adjustment": null
    }
  ],
  "viral_analysis": {
    "score_kind": "structural_potential",
    "overall_score": 0.0,
    "hook_strength": 0.0,
    "narrative_structure": "REQUIRED_NARRATIVE_STRUCTURE",
    "core_appeal": "REQUIRED_CORE_APPEAL",
    "target_audience": "REQUIRED_TARGET_AUDIENCE",
    "viral_formula": "REQUIRED_ONE_SENTENCE_FORMULA",
    "replicable_patterns": ["REQUIRED_REPLICABLE_PATTERN"],
    "potential_concerns": ["REQUIRED_CONCERN"],
    "key_moments": [
      {
        "primary_type": "hook",
        "secondary_type": "curiosity_gap",
        "start_s": 0.0,
        "end_s": 2.4,
        "title": "REQUIRED_MOMENT_TITLE",
        "description": "客观事实",
        "mechanism": "用户心理 + 内容设计",
        "score": 0.0,
        "evidence_shots": ["S001"]
      }
    ]
  },
  "reconstruction": {
    "generic_faithful_prompt": "REQUIRED_COMPLETE_FAITHFUL_PROMPT",
    "generic_enhanced_prompt": "REQUIRED_COMPLETE_ENHANCED_PROMPT",
    "variants": [
      {"dimension": "composition", "prompt": "REQUIRED_COMPLETE_COMPOSITION_VARIANT"},
      {"dimension": "lighting", "prompt": "REQUIRED_COMPLETE_LIGHTING_VARIANT"},
      {"dimension": "style", "prompt": "REQUIRED_COMPLETE_STYLE_VARIANT"}
    ],
    "consistency": {
      "named_subjects": {},
      "original_lock": "REQUIRED_ORIGINAL_LOCK",
      "style_lock": "REQUIRED_STYLE_LOCK",
      "reference_frames": [],
      "per_shot_prev_tokens": {}
    },
    "negative_constraints": ["REQUIRED_NEGATIVE_CONSTRAINT"],
    "originality_changes": ["REQUIRED_ORIGINALITY_CHANGE"]
  },
  "model_outputs": {
    "h3": [
      {
        "segment_id": "H3-001",
        "source_start_s": 0.0,
        "source_end_s": 10.0,
        "target_duration_s": 10.0,
        "mode": "Ref2VA",
        "references": ["<Video 1>", "<Picture 1>"],
        "prompt": "完整官方格式提示词"
      }
    ]
  }
}
```

示例中的 `REQUIRED_*` 仅标示必填语义；生成交付物时必须全部替换为具体内容，校验器会拒绝残留占位符。

## 不变量

- `shots` 按时间递增，互不倒置；`start_s < end_s`。
- 每个 `keyframes` 路径存在，且至少一张。
- 关键时刻位于源视频时长内，并引用存在的镜头。
- 枚举仅使用十二种受控类型。
- 所有评分位于 0–10。
- `score_kind=structural_potential` 时，不在报告中声称真实流量结果。
- 三变式的 `dimension` 必须分别为 `composition`、`lighting`、`style`。
- H3 模式仅为 `T2VA`、`I2VA`、`FL2VA`、`L2VA`、`Ref2VA`，目标时长 4–15 秒。
- `prompt` 必须完整，不得用 `...`、`同上` 或摘要代替。

## report.md 映射

面向用户的报告按以下顺序渲染：

1. 对标来源与技术信息。
2. 分镜总表和关键帧。
3. 爆款关键时刻与公式。
4. 可迁移/不可照搬。
5. 还原版、增强版、三变式。
6. 一致性锚点。
7. H3 分段索引和完整官方 Prompt。
8. 不确定项、风险和后续验证建议。
