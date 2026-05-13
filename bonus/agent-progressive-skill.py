#!/usr/bin/env python3
"""
agent-progressive-skill.py
渐进式 Skill 披露（Progressive Skill Disclosure）的 nanoAgent 实现。

在 agent-skills-mcp.py 的基础上，将 Skill 加载从"启动时全部注入"
改为"启动时仅注入摘要，按需加载全文"。

用法：
  python agent-progressive-skill.py                   # 运行 Agent（自动创建演示 Skill）
  python agent-progressive-skill.py --setup           # 仅创建演示 Skill，不运行 Agent
  python agent-progressive-skill.py --compare         # 对比两种加载方式的 token 消耗
  python agent-progressive-skill.py "你的任务"        # 运行指定任务

目录结构（会自动创建）：
  .agent/skills/
  ├── article-summarizer/
  │   └── SKILL.md
  ├── docker-deploy/
  │   └── SKILL.md
  ├── code-review/
  │   └── SKILL.md
  └── wespy-fetcher/
      └── SKILL.md
"""

import json
import os
import re
import subprocess
import sys
from pathlib import Path

MODEL = os.environ.get("OPENAI_MODEL", "gpt-4o-mini")

_client = None


def get_client():
    global _client
    if _client is None:
        from openai import OpenAI
        _client = OpenAI(
            api_key=os.environ.get("OPENAI_API_KEY"),
            base_url=os.environ.get("OPENAI_BASE_URL"),
        )
    return _client

SKILLS_DIR = ".agent/skills"

# ─────────────────────────────────────────────────────────────
# 阶段一：轻量加载——只读摘要（启动时）
# ─────────────────────────────────────────────────────────────

def parse_skill_frontmatter(skill_dir: Path) -> dict | None:
    """从 SKILL.md 的 YAML 头部提取 name 和 description，忽略正文。"""
    skill_md = skill_dir / "SKILL.md"
    if not skill_md.exists():
        return None
    content = skill_md.read_text(encoding="utf-8")
    match = re.match(r"^---\n(.*?)\n---", content, re.DOTALL)
    if not match:
        # 没有 frontmatter，退化为只用目录名
        return {"name": skill_dir.name, "description": ""}
    fm = match.group(1)
    name_m = re.search(r"^name:\s*(.+)$", fm, re.MULTILINE)
    desc_m = re.search(r"^description:\s*(.*?)(?=\n\w+:|\Z)", fm, re.DOTALL | re.MULTILINE)
    return {
        "name": name_m.group(1).strip() if name_m else skill_dir.name,
        # 多行 description 压缩成一行
        "description": " ".join(desc_m.group(1).strip().split()) if desc_m else "",
    }


def load_skill_index() -> list[dict]:
    """阶段一：加载所有 Skill 的摘要（name + description），不读正文。"""
    index = []
    skills_path = Path(SKILLS_DIR)
    if not skills_path.exists():
        return []
    for skill_dir in sorted(skills_path.iterdir()):
        if not skill_dir.is_dir():
            continue
        meta = parse_skill_frontmatter(skill_dir)
        if meta:
            index.append(meta)
    return index


# ─────────────────────────────────────────────────────────────
# 阶段二：重量加载——按需读全文（任务执行中）
# ─────────────────────────────────────────────────────────────

def load_skill_full(skill_name: str) -> str:
    """阶段二：按需加载指定 Skill 的完整 SKILL.md 内容。"""
    skill_path = Path(SKILLS_DIR) / skill_name / "SKILL.md"
    if not skill_path.exists():
        available = sorted(
            d.name for d in Path(SKILLS_DIR).iterdir() if d.is_dir()
        )
        return (
            f"错误：Skill '{skill_name}' 不存在。\n"
            f"可用 Skill：{', '.join(available)}"
        )
    content = skill_path.read_text(encoding="utf-8")
    return f"[Skill: {skill_name}]\n\n{content}"


# ─────────────────────────────────────────────────────────────
# Token 估算（粗略：1 token ≈ 4 字符，中英混合）
# ─────────────────────────────────────────────────────────────

def count_tokens_approx(text: str) -> int:
    return max(1, len(text) // 4)


# ─────────────────────────────────────────────────────────────
# 工具定义
# ─────────────────────────────────────────────────────────────

base_tools = [
    {
        "type": "function",
        "function": {
            "name": "bash",
            "description": "执行 shell 命令",
            "parameters": {
                "type": "object",
                "properties": {"command": {"type": "string"}},
                "required": ["command"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "read",
            "description": "读取文件内容",
            "parameters": {
                "type": "object",
                "properties": {"path": {"type": "string"}},
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "write",
            "description": "向文件写入内容",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "content": {"type": "string"},
                },
                "required": ["path", "content"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "load_skill",
            "description": (
                "加载指定 Skill 的完整执行指南。"
                "在执行任何 Skill 之前，必须先调用这个工具获取完整的操作步骤和注意事项，"
                "然后再按步骤执行。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "skill_name": {
                        "type": "string",
                        "description": (
                            "要加载的 Skill 名称，"
                            "例如 'article-summarizer'、'docker-deploy'、'code-review'"
                        ),
                    }
                },
                "required": ["skill_name"],
            },
        },
    },
]


def execute_tool(name: str, args: dict) -> str:
    if name == "bash":
        try:
            result = subprocess.run(
                args["command"], shell=True, capture_output=True, text=True, timeout=30
            )
            return result.stdout + result.stderr
        except Exception as e:
            return f"Error: {e}"

    elif name == "read":
        try:
            return Path(args["path"]).read_text(encoding="utf-8")
        except Exception as e:
            return f"Error: {e}"

    elif name == "write":
        try:
            path = Path(args["path"])
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(args["content"], encoding="utf-8")
            return f"已写入 {args['path']}"
        except Exception as e:
            return f"Error: {e}"

    elif name == "load_skill":
        content = load_skill_full(args["skill_name"])
        tokens = count_tokens_approx(content)
        print(f"  [ProgressiveSkill] 已加载 '{args['skill_name']}'（约 {tokens} token）")
        return content

    return f"未知工具：{name}"


# ─────────────────────────────────────────────────────────────
# System Prompt 构建
# ─────────────────────────────────────────────────────────────

def build_system_prompt(skill_index: list[dict]) -> str:
    parts = [
        "你是一个能干的助手，可以使用工具和 Skill 完成用户任务。",
        "执行任何 Skill 之前，请先用 load_skill 工具获取完整指令。",
    ]
    if skill_index:
        lines = ["", "# 可用 Skill"]
        for skill in skill_index:
            lines.append(f"- **{skill['name']}**：{skill['description']}")
        parts.append("\n".join(lines))
    return "\n\n".join(parts)


# ─────────────────────────────────────────────────────────────
# Agent 主循环
# ─────────────────────────────────────────────────────────────

def run_agent(task: str, max_iterations: int = 15) -> str:
    skill_index = load_skill_index()
    index_tokens = count_tokens_approx(
        "\n".join(f"- {s['name']}: {s['description']}" for s in skill_index)
    )
    print(f"\n[Init] 已加载 {len(skill_index)} 个 Skill 摘要（占用约 {index_tokens} token）")
    print(f"[Task] {task}\n")

    system_prompt = build_system_prompt(skill_index)
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": task},
    ]

    loaded_skills: list[str] = []

    for i in range(max_iterations):
        response = get_client().chat.completions.create(
            model=MODEL,
            messages=messages,
            tools=base_tools,
        )
        msg = response.choices[0].message
        messages.append(msg)

        if not msg.tool_calls:
            if loaded_skills:
                print(f"\n[Done] 本次任务实际加载的 Skill：{loaded_skills}")
            else:
                print("\n[Done] 本次任务未加载任何 Skill")
            return msg.content or ""

        for tc in msg.tool_calls:
            fn = tc.function.name
            args = json.loads(tc.function.arguments)
            preview = str(list(args.values())[0])[:60] if args else ""
            print(f"  [{i+1}] {fn}({preview})")

            if fn == "load_skill":
                loaded_skills.append(args.get("skill_name", ""))

            result = execute_tool(fn, args)
            messages.append(
                {"role": "tool", "tool_call_id": tc.id, "content": result}
            )

    return "已达到最大迭代次数"


# ─────────────────────────────────────────────────────────────
# 演示 Skill 文件内容
# ─────────────────────────────────────────────────────────────

DEMO_SKILLS: dict[str, str] = {
    "article-summarizer": """\
---
name: article-summarizer
description: 对 Markdown 格式文章进行结构化要点总结。Use when user asks to 总结文章、提炼要点、文章摘要、归纳核心观点、读后总结、summarize article。
---

# Article Summarizer

对已有的 Markdown 文章进行结构化要点提炼。不负责文章抓取（抓取请用 wespy-fetcher）。

## 操作流程

1. 通读全文，判断文章类型（技术 / 商业 / 观点 / 教程）
2. 根据类型确定总结侧重点：
   - 技术：侧重方案设计和论证逻辑
   - 商业：侧重数据、结论和商业洞察
   - 观点：侧重核心主张和论证方式
   - 教程：侧重关键步骤和注意事项
3. 按以下固定格式输出总结

## 输出格式

**一句话概括：**（核心主张，不超过 30 字，不是标题的改写）

**文章类型：**（技术 / 商业 / 观点 / 教程）

**核心观点（2-5 个，根据内容密度调整）：**
1. [观点]：[一句话展开]

**关键论据：**（支撑核心观点的证据，2-3 条）

**点评：**（这篇文章最大的价值，以及没有覆盖到的地方）

## 注意事项

- 适合 500-10000 字的深度文章
- 核心观点之间不能有明显重叠，每个观点必须提供独立信息
- 少于 500 字的文章请提示用户直接阅读原文
- 超过 10000 字建议先分段再逐段总结
""",
    "docker-deploy": """\
---
name: docker-deploy
description: 使用 Docker Compose 将应用部署到服务器。Use when user asks to 部署应用、docker部署、启动容器、上线服务、发布新版本。
---

# Docker Deploy

使用 Docker Compose 完成应用的构建、部署和验证。

## 前置检查

1. 确认 Dockerfile 存在且语法正确
2. 确认 docker-compose.yml 配置正确，环境变量已注入
3. 确认目标服务器可访问（SSH 或 CI/CD 环境）

## 部署流程

```bash
# 1. 构建镜像
docker-compose build --no-cache

# 2. 平滑停止旧版本
docker-compose down

# 3. 启动新版本（后台运行）
docker-compose up -d

# 4. 验证运行状态
docker-compose ps
docker-compose logs --tail=50
```

## 验收标准

- `docker-compose ps` 所有服务状态为 `Up`
- 日志中无 ERROR 级别输出
- 健康检查接口（如 /health）返回 200

## 回滚方案

```bash
docker-compose down
git checkout HEAD~1
docker-compose up -d
```

## 注意事项

- 生产环境部署前必须在 staging 验证
- 部署前备份数据库
- 保留最近 3 个版本的镜像以便快速回滚
""",
    "code-review": """\
---
name: code-review
description: 对代码进行系统性审查，发现潜在问题并给出改进建议。Use when user asks to 代码审查、review代码、检查代码、code review、看看我的代码、帮我看看这段代码。
---

# Code Review

对代码进行系统性审查，按优先级输出问题和改进建议。

## 审查维度（优先级从高到低）

**P0 - 安全漏洞（必须修复）：**
- SQL 注入、XSS、命令注入
- 敏感信息硬编码（密钥、密码、Token）
- 权限校验缺失或绕过

**P1 - 逻辑错误（强烈建议修复）：**
- 边界条件处理（空值、越界、溢出）
- 错误处理完整性
- 并发安全性（竞态条件、死锁）

**P2 - 代码质量（建议改进）：**
- 函数单一职责
- 变量和函数命名清晰度
- 重复代码（DRY 原则）

**P3 - 性能（可选优化）：**
- N+1 查询问题
- 不必要的循环或重复计算

## 操作流程

1. 先读完整个文件，了解整体逻辑，不要边读边评论
2. 记录所有发现的问题，按优先级分类
3. 按格式输出，发现 P0 问题时最先展示

## 输出格式

每条问题格式：
> [优先级] 文件名:行号 — 问题描述
> 建议：具体改法（给代码示例，不给泛泛建议）

## 注意事项

- 发现 P0 问题时立即在输出开头标注"⚠️ 发现安全问题"
- 如果代码整体质量良好，明确说出"整体质量良好，无 P0/P1 问题"
- 不要对合理的编码选择（如命名风格）过度评论
""",
    "wespy-fetcher": """\
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
""",
}


def setup_demo_skills(verbose: bool = True) -> None:
    """创建演示用的 Skill 文件。"""
    skills_path = Path(SKILLS_DIR)
    for skill_name, content in DEMO_SKILLS.items():
        skill_dir = skills_path / skill_name
        skill_dir.mkdir(parents=True, exist_ok=True)
        (skill_dir / "SKILL.md").write_text(content, encoding="utf-8")

    if verbose:
        print(f"✓ 已创建 {len(DEMO_SKILLS)} 个演示 Skill，路径：{SKILLS_DIR}/")
        print()
        for name, content in DEMO_SKILLS.items():
            tokens = count_tokens_approx(content)
            # 只取 description 行（一行摘要）
            desc_m = re.search(r"^description:\s*(.+)$", content, re.MULTILINE)
            desc_preview = ""
            if desc_m:
                desc_preview = desc_m.group(1)[:50]
            print(f"  {name}")
            print(f"    摘要：{desc_preview}...")
            print(f"    全文：约 {tokens} token")
        print()


def show_token_comparison() -> None:
    """对比饿汉式加载与渐进式加载的 token 消耗。"""
    skill_index = load_skill_index()
    if not skill_index:
        print("未找到 Skill。正在创建演示 Skill...")
        setup_demo_skills()
        skill_index = load_skill_index()

    # 饿汉式加载：全部 Skill 全文注入 system prompt
    eager_parts = []
    for skill in skill_index:
        full = load_skill_full(skill["name"])
        eager_parts.append(full)
    eager_tokens = sum(count_tokens_approx(c) for c in eager_parts)

    # 渐进式加载：只注入摘要列表
    index_lines = [f"- {s['name']}: {s['description']}" for s in skill_index]
    progressive_tokens = count_tokens_approx("\n".join(index_lines))

    # 单次加载一个 Skill 的成本
    avg_full_tokens = eager_tokens // len(skill_index) if skill_index else 0

    print()
    print("=" * 55)
    print(f"  Token 消耗对比（共 {len(skill_index)} 个 Skill）")
    print("=" * 55)
    print(f"  饿汉式加载（旧方式）：{eager_tokens:,} token（启动时全部注入）")
    print(f"  渐进式加载（新方式）：{progressive_tokens:,} token（只注入摘要）")
    print(f"  启动节省：          {eager_tokens - progressive_tokens:,} token"
          f"（节省 {(1 - progressive_tokens / eager_tokens) * 100:.0f}%）")
    print()
    print(f"  按需加载一个 Skill 的额外成本：约 {avg_full_tokens} token")
    print(f"  → 任务中加载 1 个 Skill 总计：{progressive_tokens + avg_full_tokens} token")
    print(f"    仍比饿汉式少：{eager_tokens - progressive_tokens - avg_full_tokens} token")
    print("=" * 55)
    print()
    print("  结论：Skill 越多，渐进式加载的优势越显著。")
    print(f"  当 Skill 数量翻倍到 {len(skill_index) * 2} 个时：")
    print(f"    饿汉式加载约 {eager_tokens * 2:,} token")
    print(f"    渐进式加载约 {progressive_tokens * 2 + avg_full_tokens:,} token（含 1 次按需加载）")
    print()


# ─────────────────────────────────────────────────────────────
# 入口
# ─────────────────────────────────────────────────────────────

def main() -> None:
    args = sys.argv[1:]

    if "--setup" in args:
        setup_demo_skills()
        return

    if "--compare" in args:
        setup_demo_skills(verbose=False)
        show_token_comparison()
        return

    # 确保演示 Skill 存在
    if not Path(SKILLS_DIR).exists() or not any(Path(SKILLS_DIR).iterdir()):
        print("未找到 Skill 目录，正在创建演示 Skill...")
        setup_demo_skills()

    # 过滤掉 flag 参数，剩余部分作为任务
    task_parts = [a for a in args if not a.startswith("--")]
    task = " ".join(task_parts) if task_parts else (
        "帮我用 article-summarizer Skill 总结以下文章的核心要点：\n\n"
        "本文探讨了 Agent 时代的 API 设计变革。传统 REST API 为人类设计，"
        "采用分页、确认弹窗等交互模式，这些模式会严重拖慢 Agent 的执行效率。"
        "作者认为，Agent 友好的 API 应该提供意图级接口而非操作级接口，"
        "让 Agent 用一次调用完成原本需要多步的任务。"
        "未来 API 文档的主要读者将从人类开发者变为 Agent，可读性需要为机器优化。"
    )

    result = run_agent(task)
    print()
    print(result)


if __name__ == "__main__":
    main()
