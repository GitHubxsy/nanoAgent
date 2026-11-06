# 从零开始理解 Agent（一）· Papermorph 视频版

根据 `agent/01-essence/agent-essence.md` 改编，使用 Papermorph 的 SVG 播放器、中文 TTS 与逐帧视频导出。
不是复用此前的 HyperFrames 视频。原文章、讲义和网站不变。

成片：`exports/agent-01-papermorph.mp4`，3 分 58 秒，1080p，中文配音和可开关的中文字幕轨道。
配套字幕：`exports/ch01.srt`。检查范围见 `QA.md`。

1.15 倍速版：`exports/agent-01-papermorph-1.15x.mp4`，约 3 分 27 秒，保持人声音调，原速版保留。
新版字幕固定在画面底部中央，32px、单行，长句按 TTS 词时间拆为 74 条短字幕。
字幕已烧录，避免播放器覆盖字号和位置；观看时无需再加载 SRT，以免重复显示。
重新生成：`uv run --with imageio-ffmpeg python tools/agent-first/speedup.py`。
此命令使用原速导出 `exports/ch01.mp4` 和 TTS 生成的 `content/agent-first/ch01/narration.zh.timings.json`，需先完成下方配音与导出步骤。

[下载最终视频](exports/agent-01-papermorph-1.15x.mp4) · [下载配套字幕](exports/agent-01-papermorph-1.15x.srt)

## 内容

约 4 分钟，10 段讲解：文本建议与实际行动、大脑与手脚、工具说明与执行分工、
统计与写文件的三轮示例、消息历史、停止条件、安全边界、总结。
示例数字 42 来自原文，并非本次脚本实测；视频没有调用任何大模型 API。

## 本地播放

从本目录运行：

```sh
python3 -m http.server 8776 --bind 127.0.0.1 --directory site
```

打开 `http://127.0.0.1:8776/agent-first/`，可暂停、逐段播放、调速、开关字幕。

## 修改与导出

Papermorph 安装在 `~/.codex/skills/papermorph`。安装依赖：`uv`、`ffmpeg`、Playwright。
编辑 `content/agent-first/ch01/narration.zh.json` 和 `site/agent-first/ch01/lesson.js`。

```sh
node build.mjs
uv run --with edge-tts python ~/.codex/skills/papermorph/scripts/tts.py content/agent-first/ch01/narration.zh.json site/agent-first/ch01/audio/zh
python3 ~/.codex/skills/papermorph/scripts/level.py --lufs -16 --peak -1.5 site/agent-first/ch01/audio/zh/*.mp3
python3 ~/.codex/skills/papermorph/scripts/lint.py site/agent-first ch01
uv run --with playwright python ~/.codex/skills/papermorph/scripts/check.py ch01 --url http://127.0.0.1:8776/agent-first/
uv run --with playwright python tools/agent-first/verify.py
uv run --with playwright --with numpy python ~/.codex/skills/papermorph/scripts/export.py ch01 --url http://127.0.0.1:8776/agent-first/ --out exports --height 1080 --fps 30 --jobs 4
```

如果机器设置了代理，导出命令需去掉 `http_proxy`、`https_proxy`、`all_proxy` 及对应大写环境变量，避免 FFmpeg 将本地音频请求发送到代理。
没有 Playwright Chromium 时，设置 `CHROME` 为本机 Chrome 可执行文件。

## 文件与许可

- `site/agent-first/`：可独立运行的静态动画与配音。
- `exports/`：仅提交最终 1.15 倍速 MP4 与配套 SRT，原速版和中间文件保留本地。
- `books/agent-first/`：风格、分镜和检查记录。
- `site/agent-first/lib/LICENSE-Papermorph`：第三方引擎 MIT 许可。

配音与制作均在当前会话完成，无独立审片模型；成片仍待作者观看确认。
