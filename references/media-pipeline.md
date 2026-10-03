# 媒体管线：参数与复用

脚本以skill根目录为基准，输入/输出指向用户本次工程。首次配置或报错时用 `scripts/check_environment.py --require-core`；不要每轮重复探测。

本地输入直接运行分镜，清单包含来源路径、SHA-256与大小。链接运行 `scripts/acquire_video.py URL --output-dir RUN/source`；源manifest记录脱敏来源。公开视频页面需yt-dlp，直接视频URL可标准库下载。登录、Cookie、验证码、DRM或付费限制不绕过；请用户提供本地文件。

核心需要FFmpeg/FFprobe，可用FFMPEG_BIN、FFPROBE_BIN、YTDLP_BIN指定。依赖缺失说明影响；按已有授权处理安装。

## 分镜参数

`segment_video.py VIDEO --output-dir RUN/deconstruction --reuse`。

- 默认分析全视频；`--max-seconds N`明确局部范围。
- `--scene-threshold 0.35`调RGB变化检测灵敏度，包含暗色/色相切换；检测仍只是候选。
- `--min-shot-seconds 0.10`避免轻易吞短镜；调整时需视觉核对。
- `--extra-frame-interval N`只用于确有必要的长动作。
- `--extract-clips`确需独立片段时使用；`--no-audio`仅视觉任务使用。
- `--reuse`校验源/参数/产物哈希后返回已有清单；不重新解码。
- 源、设置或产物变化时缓存拒绝；用新目录，或确认属于同一任务后`--force`重建。

一次批量抽取去重帧，记录实际PTS、源归零时刻、帧序号和哈希；首末帧与生成目标端点分别记录。帧末持续时间未知时不从平均帧率伪造精确终点。

输出shot_manifest.json、frame_index.html、frames/；可选clips/、audio.wav。单声道16kHz WAV用于分析，保真交接使用原音频流。每次运行目录独立；续作复用同一事实源与有效产物。

错误码：1参数/普通错误，2依赖/输入/解码错误，3下载失败，4已有输出或缓存失效。
