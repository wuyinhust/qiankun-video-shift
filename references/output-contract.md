# 统一事实与交付契约（v2）

写入或修改 `analysis.json` 时读取。只保留一份事实源；`derived` 由脚本生成。

## 先从媒体清单起草

```sh
python3 scripts/seed_analysis.py run/deconstruction/shot_manifest.json --output run/analysis.json --workflow prompt
```

草稿只复制时间、帧证据和哈希，没有观察事实或已复核声明。完整迁移加 `--workflow remix --intent adapted`。

必需顶层：`schema_version="2.0" / workflow=prompt|remix / intent=faithful|adapted / analysis_status=complete|partial / source / shots / evidence / facts / jobs / audio_plan`。

| 字段 | 必需内容 |
|---|---|
| source | video_path、sha256、duration_s、analysis_range_s；保留last_frame_time_s与time_origin_pts_s，范围标明完整或局部分析 |
| shots | id、range_s、end_condition；切点按源时钟，连续覆盖分析范围 |
| evidence | id、kind=frame\|clip\|audio、range_s、path、sha256、source_sha256；实际查看的媒体和范围 |
| facts | id、shot_id、kind、range_s、status、text、evidence_ids；每条一句关键可观察内容 |
| jobs | id、mode、source_range_s、target_range_s、opening_fact_ids、closing_fact_ids、references |
| audio_plan | method=none\|postproduction_copy\|reference\|recreate、content_status=verified\|unavailable\|no_track\|not_requested |

事实 kind：identity、initial、state、action、camera、ending、transition、dialogue、soundscape、music。status：observed、uncertain、user_requested。不确定事实不进入生成文本；新增内容需要 adapted 和 request。动作须引用连续片段或多个不同时刻的帧；声音须音频证据。可用 `after` 引用实际先结束的前驱。

`essential=true` 只标少量决定性的视角、初态、动作结果和截止状态。它来自实际媒体，不能为通过校验随意取消。`end_condition=settled|ongoing|cutoff|unknown` 不补造结局。

源事实 `text` 保持不变。目标改写用 `target_text / target_request`，有意省略用 `omit / target_request`，并列入顶层 `intentional_deviations`。英文模型段由英文事实/目标文案形成；台词和可见文字保留目标语言。不要把不清楚的内容润色成事实。

最小填写示例：假设**实际观察**是一镜4秒、全程静态红杯，首/末帧证据为E0001/E0003，末帧3.96秒。保留seed生成的source/evidence，更新以下字段；实际任务必须替换时间、ID和观察，不能照抄示例事实。

```json
{
  "analysis_status":"complete",
  "shots":[{"id":"S001","range_s":[0,4],"end_condition":"settled"}],
  "facts":[
    {"id":"F1","shot_id":"S001","kind":"initial","range_s":[0,0],"status":"observed","text":"A red cup sits on a white table.","evidence_ids":["E0001"],"essential":true},
    {"id":"F2","shot_id":"S001","kind":"ending","range_s":[3.96,3.96],"status":"observed","text":"The cup remains in the same position at the end.","evidence_ids":["E0003"],"essential":true}
  ],
  "jobs":[{"id":"J1","mode":"generic","source_range_s":[0,4],"target_range_s":[0,4],"opening_fact_ids":["F1"],"closing_fact_ids":["F2"],"references":[]}],
  "audio_plan":{"method":"none","content_status":"not_requested"}
}
```

有动作/切镜就补相应事实和证据；多镜通用Prompt可用一个覆盖全片的job，各镜事实仍分属对应shot。局部修改用 `inspect_analysis.py ... --shot S001` 或 `--fact F2`，返回相关事实/证据、邻接转场boundary_facts及受影响job的边界ID，无需读全片job。换色也检查前镜“切成该颜色”等入镜描述。保留text，增加target_text与target_request，intent改adapted并填写intentional_deviations。

## 生成单元与模型

mode 为 generic、T2VA、I2VA、FL2VA、L2VA、Ref2VA。通用母版不需要模型能力。H3 需已核实的 `capability`：min_duration_s、max_duration_s、modes、source、checked_at；官方格式由 `$h3-prompt-writing` 核对。不要假设分析视频等于提交视频参考。

每段起止事实绑定该段边界附近的实际状态（允许末帧与排他终点的差异）。连续镜头分段须拆长动作并建立切分状态。逐镜关键帧模式在一个源镜范围内；文字多镜任务遵守当前平台能力。每段本地重置 Shot/Picture 编号，源/目标时间映射独立保留。

references 每项 `label / path / sha256`，关键帧另需 `source_time_s`，Ref2VA另需 description、retention=fully_copy|partially_copy|reference。原创首帧可为目标生成图，source_time_s表示它应表现的源边界状态，不能把该图当源证据。

## 编译与复核

```sh
python3 scripts/compile_analysis.py run/analysis.json
python3 scripts/validate_analysis.py run/analysis.json --check-files
```

编译生成通用/H3块、独立首帧、Motion、尾态、素材与装配交接。修改 derived 会被拒绝；输入改变让旧复核失效。短任务只展示用户所需的可复制部分。

从媒体提出必保项 → 找到事实ID → 核对最终句，压缩或翻译后再查。真实查看与核对后才填写：

```json
{"status":"reviewed","input_digest":"当前compilation.input_digest","notes":"实际查看与语义核对内容","evidence_ids":["实际看过的证据ID"],"anchors_checked":true,"tail_checked":true}
```

保存到 `review` 后运行 `validate_analysis.py ... --check-files --require-reviewed`。哈希/声明不能证明看懂画面。未决必保项保持草稿；不要自填用户回复或把未观看标记成已看。

## 声音与完整迁移

分析用16kHz单声道WAV不替代原音频流。声音存在、内容核听、用户目标、执行路线分别记录。已授权保真复用需 `authorized_reuse=true / stream_index / start_pts_s`；编译交接按源/目标映射只铺一次原音轨、移除生成声音，口型另验。改时长或重排时选择明确的重制/编辑方案。Ref2VA须真实素材与支持该关系的入口。

remix 另需 `viral_analysis.viral_formula` 和 `replacement_map`；跨镜系统与语义事件见 [production-plan.md](production-plan.md)。真实流量分析保留数据来源；没有流量数据只谈结构潜力。

v1仍可运行结构检查，现已检查逐镜字段和完整覆盖。v1没有事实与派生绑定，不能声明严格复核；继续任务时用已有媒体清单起草v2并复用已核实的观察，缺少证据再局部补看。
