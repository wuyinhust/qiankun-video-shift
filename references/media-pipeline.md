# 媒体管线

本参考只在第一式、第二式或媒体脚本报错时读取。

## 能力与依赖

| 能力 | 必需工具 | 降级 |
|---|---|---|
| 本地文件登记 | Python 3 标准库 | 无需额外工具 |
| 直接视频 URL 下载 | Python 3 标准库 | 仅接受 HTTP(S) 且响应为视频/二进制 |
| 抖音、TikTok、YouTube 等页面链接 | `yt-dlp` | 让用户自行下载并提供本地文件 |
| 技术参数、切镜、抽帧、音频 | `ffmpeg` + `ffprobe` | 无核心工具时停止第二式，不用猜测代替 |

三个可执行文件可以通过 `FFMPEG_BIN`、`FFPROBE_BIN`、`YTDLP_BIN` 指定。解析顺序为显式环境变量、PATH、常见本地安装位置、现有 Codex/Agents Skill 中已安装的静态 FFmpeg；脚本不会自动安装依赖，也不会读取浏览器 Cookie。

## 推荐工作目录

每次运行使用独立目录，避免覆盖其他任务：

```text
run/<source-id>/
├── source/
│   └── source_manifest.json
├── deconstruction/
│   ├── shot_manifest.json
│   ├── frame_index.html
│   ├── audio.wav
│   └── frames/
├── analysis.json
├── report.md
└── prompts/
```

`source-id` 可以使用文件名加 SHA-256 前八位。不要用未清洗的网页标题直接创建路径。

## 第一式命令

本地文件，只登记不复制：

```bash
python3 scripts/acquire_video.py ./reference.mp4 --output-dir run/source
```

复制本地文件到任务目录：

```bash
python3 scripts/acquire_video.py ./reference.mp4 --output-dir run/source --copy-local
```

公开链接：

```bash
python3 scripts/acquire_video.py "https://example.com/video" --output-dir run/source
```

脚本优先使用 `yt-dlp` 处理页面链接；若工具不存在或下载失败，仅在响应确实是直接视频时才走标准库下载。登录、付费、验证码、Cookie 或 DRM 场景不降级绕过。

## 第二式命令

默认进行场景检测，每镜抽首、中、尾帧，并提取单声道 16 kHz WAV：

```bash
python3 scripts/segment_video.py ./reference.mp4 --output-dir run/deconstruction
```

常用参数：

- `--scene-threshold 0.35`：越高切镜越少；快切视频可降至 0.25–0.30，闪光/镜头抖动严重时可升至 0.40–0.50。
- `--min-shot-seconds 0.50`：短于该值的镜头并入相邻镜头。
- `--max-seconds 120`：限制分析时长；设为 `0` 表示不限。
- `--max-shots 80`：超过后脚本逐步提高阈值，避免失控地产生数百镜头。
- `--extra-frame-interval 2.0`：对长镜头每两秒补一帧；默认关闭。
- `--extract-clips`：额外输出每镜 MP4，适用于判断复杂运镜或动作。
- `--no-audio`：不提取音轨。
- `--force`：允许覆盖同一输出目录中的脚本产物。

## 混合观察规则

1. `shot_manifest.json` 是时间轴权威。
2. 所有关键帧都必须被查看；不能用整段视频直读取代。
3. 整段视频或逐镜短片用于补足帧间信息：动作速度、镜头轨迹、转场、口型、声音与节奏。
4. 静态帧和视频直读结论冲突时，以可定位的镜头短片复核，并在 `analysis.json` 记录不确定性。
5. 音轨存在时，先转录或人工确认台词；听不清的内容写 `unknown`，不要补写。

## 退出码

- `0`：成功。
- `1`：参数或普通运行错误。
- `2`：输入、依赖或解码错误。
- `3`：下载失败。
- `4`：输出冲突，需要新目录或 `--force`。
