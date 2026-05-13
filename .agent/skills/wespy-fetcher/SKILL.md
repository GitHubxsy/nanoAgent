---
name: wespy-fetcher
description: 抓取微信公众号文章并转换为 Markdown 格式保存到本地。Use when user asks to 抓取公众号、下载微信文章、保存微信文章、mp.weixin.qq.com to markdown、公众号转 Markdown。
---

# WeSpy Fetcher

封装 WeSpy 工具，完整支持微信公众号单篇抓取、专辑批量下载和多格式输出。

## 使用方法

```bash
# 单篇文章（默认输出 Markdown）
python3 scripts/wespy_cli.py "https://mp.weixin.qq.com/s/xxxxx"

# 专辑批量下载（最多 20 篇）
python3 scripts/wespy_cli.py "https://mp.weixin.qq.com/mp/appmsgalbum?..." --max-articles 20

# 只获取专辑文章列表（不下载内容）
python3 scripts/wespy_cli.py "https://..." --album-only

# 输出 JSON 格式
python3 scripts/wespy_cli.py "https://..." --format json
```

## 实现说明

- 优先使用本地源码路径 `~/Documents/project/WeSpy`
- 若本地不存在，自动执行 `git clone https://github.com/tianchangNorth/WeSpy.git` 到该目录
- 通过导入 `wespy.main.main` 直接调用上游 CLI，保持行为一致

## 输出文件

- 默认保存到 `~/Documents/articles/`
- 文件名格式：`YYYY-MM-DD-文章标题.md`
- 图片下载到同目录的 `images/` 子文件夹

## 注意事项

- 微信公众号有反爬机制，首次运行可能需要扫码登录
- Cookie 保存在 `~/.wespy/cookies.json`，有效期约 7 天
- 企业号文章和部分付费文章可能无法抓取
