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

## 三条核心路径

- 快速反推：给视频，输出通用Prompt；指定H3才加载其官方格式。逐镜首帧/Motion按需交付。
- 原创迁移：保留吸引力结构，替换人物、产品、台词等；用跨镜视听系统和语义事件交接制作。
- 局部修订：复用已有analysis.json和媒体，只读/改受影响镜头或系统。

默认不输出三变式、双模式、完整报告，也不安装生成引擎。需要这些产物时可明确要求。四式主线和单一事实源保持；事实、证据、目标改写与派生输出分开记录。

验证：`python3 -m unittest discover -s tests -v`。实际媒体集成测试需要FFmpeg/FFprobe；没有工具时会明确跳过，不能视为媒体通过。

流程与按需参考见SKILL.md。升级与效率证据见validation/，方法来源见THIRD_PARTY_NOTICES.md。
