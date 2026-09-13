# 乾坤大挪移 · qiankun-video-shift

将操作者提供的视频拆解为分镜证据、叙事结构与原创迁移方案。

## 安装与使用

从本仓库下载 ZIP 并解压，或复制 GitHub 页面提供的 Clone 地址执行 git clone。让 Codex、WorkBuddy 或其他支持文件读取和脚本执行的智能体读取仓库根目录 SKILL.md。无需依赖原作者电脑上的全局 Skill 目录。

依赖 Python 3、FFmpeg、ffprobe；公开视频平台下载按需使用 yt-dlp。安装后在仓库目录运行：

```sh
python3 scripts/check_environment.py --require-core
```

## 跨电脑输入约定

- 参考视频由操作者在当前任务上传或提供可访问下载链接。不得搜索其他电脑路径、历史聊天或本机目录来补齐素材。
- 输出放在操作者指定的本次工程目录；允许处理本次上传或下载的文件。
- 云端 IndexTTS 由操作者提供服务 URL、调用文档、授权方式和音色 ID，或另外上传授权的音色参考素材。不得假定 localhost、内网 IP 或已有本地服务。
- 缺失输入明确索取；凭据通过执行环境安全注入，不写入仓库。
- 本 Skill 负责分析和迁移。配音驱动成片可另安装 https://github.com/Vincentwei1021/video-talkcraft ，按其说明使用 Remotion。
- Remotion 任务不需要安装 HyperFrames，也不需要 H3 专属依赖；只有明确使用 H3 时才读取对应路由并安装其中指向的官方 Skill。

完整流程、脚本参数和产物契约见 SKILL.md 与 references/。方法来源见 THIRD_PARTY_NOTICES.md。
