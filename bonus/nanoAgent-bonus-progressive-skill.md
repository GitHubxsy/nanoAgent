# 从零开始理解 Agent（番外篇）：Skill 的渐进式披露——不一次把所有工作手册塞给 Agent

> **「从零开始理解 Agent」系列番外** —— 如果你读过第三篇《Rules、Skills 与 MCP》，你已经知道 Skill 是怎么注入 system prompt 的：启动时全部加载、全部注入。这篇番外要讲的是：当 Skill 越积越多，这种做法会出什么问题，以及真实的 Agent 系统是怎么解决的。

在「从零开始理解 Agent」的第三篇里，我们有一段这样的代码：

```python
if skills:
    context_parts.append(
        "\n# Skills\n" + "\n".join(
            [f"- {s['name']}: {s.get('description', '')}" for s in skills]
        )
    )
```

把所有 Skill 的内容加载出来，全部注入 system prompt，完事。

当时的 `agent-skills-mcp.py` 里只有两三个 Skill，这样写没有任何问题。

**但如果你有 50 个 Skill 呢？**

---

## 开场：一个等比级数的问题

想象你在一家公司用上了 Agent。

刚开始，你为 Agent 写了 3 个 Skill：抓取公众号文章、结构化总结、代码审查。Agent 好用，于是你继续写：Docker 部署、数据库查询、邮件起草、报告生成……

半年后，你的 `.agent/skills/` 目录里有了 30 个 Skill。一年后，50 个。如果你在一个团队里，团队成员各自贡献 Skill，这个数字可能还要翻倍。

每次 Agent 启动，`load_skills()` 把这 50 个 Skill 的全文内容一股脑塞进 system prompt。

**这带来了一个等比级数的问题。**

---

## 一、数字说话：Skill 越多，"税"越重

一个写得认真的 SKILL.md 有多少 token？我们拿实际文件来量：

| Skill | 内容 | 约 token 数 |
|-------|------|------------|
| `wespy-fetcher` | 功能描述 + 命令示例 + 实现说明 | ~180 |
| `article-summarizer` | 流程 + 输出格式 + 注意事项 | ~250 |
| `docker-deploy` | 前置检查 + 部署命令 + 回滚方案 | ~300 |
| `code-review` | 四个优先级维度 + 输出格式 | ~350 |

取一个保守的平均值：每个 Skill **250 token**。

| Skill 数量 | 每次调用消耗 | 占 128K 上下文的比例 |
|-----------|------------|---------------------|
| 5 个      | 1,250 token | ~1%，可以忽略       |
| 20 个     | 5,000 token | ~4%，开始有感觉      |
| 50 个     | 12,500 token | **~10%，每次都在交"入场税"** |
| 100 个    | 25,000 token | **~20%，上下文已经烧掉五分之一** |

更糟糕的是：**这 10-20% 的上下文，绝大多数都是浪费的。**

一次任务通常只用到 1-3 个 Skill。另外 47-49 个 Skill 的内容坐在那里，占着空间，对这次任务毫无贡献。它们是纯粹的"上下文税"。

> 用第六篇《上下文压缩》里的说法：这是"旧的无用内容淹没关键信息"的一个特殊案例——只不过这次的"无用内容"是在任务开始之前就存在的。

---

## 二、两阶段加载：先看摘要，再读全文

解决方案直觉上很简单，和你读书的方式一样：

**先看目录，需要哪章再去读哪章。**

把 Skill 加载拆成两个阶段：

**阶段一：启动时（轻量）**

只加载每个 Skill 的"一句话摘要"——名称 + 一行描述。这些信息让 Agent 知道"我有哪些能力"，但不告诉它"每个能力的具体执行步骤"。

```
# 可用 Skill（共 4 个）
使用 load_skill(skill_name) 获取某个 Skill 的完整指令后再执行。

- article-summarizer：对 Markdown 文章进行结构化要点总结
- docker-deploy：使用 Docker Compose 将应用部署到服务器
- code-review：对代码进行全面审查，发现潜在问题并给出改进建议
- wespy-fetcher：抓取微信公众号文章并转换为 Markdown
```

这 4 行文字大约 80 token，和 4 个完整 SKILL.md 的 1,080 token 相比，节省了 93%。

**阶段二：按需加载（重量）**

给 Agent 一个新工具：`load_skill(skill_name)`。当 Agent 判断需要执行某个 Skill 时，先调用这个工具，加载完整的 SKILL.md 内容，然后再执行。

```
用户：帮我总结一下这篇文章
         ↓
Agent 扫描摘要，匹配到 article-summarizer
         ↓
调用 load_skill("article-summarizer")  ← 此时才加载全文
         ↓
读取完整的操作流程、输出格式、注意事项
         ↓
按 Skill 的指令执行总结任务
```

**这就是渐进式披露（Progressive Disclosure）：先展示存在，按需展示细节。**

```
┌─────────────────────────────────────────────────────────┐
│                   旧方式（饿汉式加载）                     │
│                                                          │
│  启动 → 全部 Skill 全文内容 → system prompt              │
│          [250+250+300+350+...] token                     │
│          ↑ 任务开始前就全部消耗掉了                        │
└─────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────┐
│                   新方式（懒加载）                         │
│                                                          │
│  启动 → 仅 Skill 摘要 → system prompt                   │
│          [~20] token × N 个 Skill                       │
│                                                          │
│  任务中 → Agent 调用 load_skill("xxx")                   │
│          [250] token，只加载用到的那个                    │
└─────────────────────────────────────────────────────────┘
```

---

## 三、Claude Code 也是这样做的

这不是理论设计，而是已经在生产中运行的模式。

如果你用过 Claude Code（或者观察过它的运行方式），你会注意到 Claude Code 里有一个叫 **ToolSearch** 的工具。系统在启动时这样告诉 Agent：

```
The following deferred tools are now available via ToolSearch.
Their schemas are NOT loaded — calling them directly will fail.
Use ToolSearch with query "select:<name>" to load tool schemas
before calling them:

ExitPlanMode
Monitor
NotebookEdit
mcp__github__add_issue_comment
mcp__github__create_pull_request
...（几十个工具名称，没有参数定义）
```

注意这里说的是 **"schemas are NOT loaded"**——工具名字列在这里，但每个工具的参数定义（schema）还没有加载。你只知道它存在，不知道它怎么调用。

如果 Agent 直接调用这些工具，会失败：`InputValidationError`。它必须先通过 `ToolSearch` 加载工具的 schema，然后才能调用。

**这正是把同样的渐进式披露思想用在了工具上。**

| | 工具（Tools） | 技能（Skills） |
|---|---|---|
| **阶段一（轻量）** | 工具名称列表 | Skill 名称 + 一行描述 |
| **阶段二（按需）** | 调用 ToolSearch 加载 schema | 调用 load_skill 加载全文 |
| **触发方式** | Agent 需要用某个工具时 | Agent 需要执行某个 Skill 时 |
| **节省的内容** | 参数定义 JSON（每个工具约 50-200 token） | 执行步骤 Markdown（每个 Skill 约 200-500 token） |

两者是完全对称的。Claude Code 把这个模式系统化地应用在了它所有可扩展的组件上：**先披露存在，再按需加载细节。**

> **一个有趣的观察**：Anthropic 在他们自己的番外篇文章《Harness Engineering》里提到了这个机制，用的词是 **"Skills 渐进加载"**（progressive skill loading）——不是一次性把所有 Skill 塞进 prompt，而是按需加载。这篇番外正是对那一句话的完整展开。

---

## 四、nanoAgent 的实现

让我们把这个思路用代码实现出来。配套脚本是 [`agent-progressive-skill.py`](./agent-progressive-skill.py)，在 `agent-skills-mcp.py` 基础上增加了约 60 行代码。

核心改动有三处。

### 4.1 只读摘要，不读全文

```python
def load_skill_index() -> list[dict]:
    """阶段一：只加载名称和描述（轻量）"""
    index = []
    for skill_dir in sorted(Path(SKILLS_DIR).iterdir()):
        if not skill_dir.is_dir():
            continue
        meta = parse_skill_frontmatter(skill_dir)
        if meta:
            index.append(meta)
    return index

def parse_skill_frontmatter(skill_dir: Path) -> dict | None:
    """从 SKILL.md 的 YAML 头部提取 name 和 description"""
    skill_md = skill_dir / "SKILL.md"
    if not skill_md.exists():
        return None
    content = skill_md.read_text()
    match = re.match(r'^---\n(.*?)\n---', content, re.DOTALL)
    if not match:
        return {"name": skill_dir.name, "description": ""}
    fm = match.group(1)
    name_m = re.search(r'^name:\s*(.+)$', fm, re.MULTILINE)
    desc_m = re.search(r'^description:\s*(.*?)(?=\n\w+:|\Z)', fm, re.DOTALL | re.MULTILINE)
    return {
        "name": name_m.group(1).strip() if name_m else skill_dir.name,
        "description": ' '.join(desc_m.group(1).strip().split()) if desc_m else ""
    }
```

对比 `agent-skills-mcp.py` 里的 `load_skills()`——那个函数读取的是 JSON 文件里的完整 Skill 对象（包含所有字段）。这里我们只读 SKILL.md 顶部的几行 YAML，其他内容暂时不动。

### 4.2 按需加载全文

```python
def load_skill_full(skill_name: str) -> str:
    """阶段二：按需加载完整 SKILL.md（重量，仅在需要时调用）"""
    skill_path = Path(SKILLS_DIR) / skill_name / "SKILL.md"
    if not skill_path.exists():
        available = [d.name for d in Path(SKILLS_DIR).iterdir() if d.is_dir()]
        return f"错误：Skill '{skill_name}' 不存在。可用 Skill：{', '.join(available)}"
    return skill_path.read_text()
```

### 4.3 把 load_skill 注册为工具

```python
load_skill_tool = {
    "type": "function",
    "function": {
        "name": "load_skill",
        "description": (
            "加载指定 Skill 的完整执行指南。"
            "在执行任何 Skill 之前，必须先调用这个工具获取完整的操作步骤。"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "skill_name": {
                    "type": "string",
                    "description": "要加载的 Skill 名称，如 'article-summarizer'、'docker-deploy'"
                }
            },
            "required": ["skill_name"]
        }
    }
}
```

工具执行时，把全文内容作为 tool result 返回给 LLM：

```python
elif name == "load_skill":
    content = load_skill_full(args["skill_name"])
    tokens = count_tokens_approx(content)
    print(f"  [ProgressiveSkill] 已加载 {args['skill_name']}（约 {tokens} token）")
    return content
```

### 4.4 system prompt 的变化

旧方式（agent-skills-mcp.py）：

```python
# 注入全部 Skill 的完整内容
context_parts.append(
    "\n# Skills\n" + "\n".join(
        [f"- {s['name']}: {s.get('description', '')}" for s in skills]  # 全文
    )
)
```

新方式（agent-progressive-skill.py）：

```python
# 只注入摘要，告诉 Agent 如何按需加载
lines = [
    "# 可用 Skill",
    "执行任何 Skill 之前，请先调用 load_skill(skill_name) 获取完整指令。",
    ""
]
for skill in skill_index:
    lines.append(f"- **{skill['name']}**：{skill['description']}")
context_parts.append("\n".join(lines))
```

两段代码的物理差别只有几行，但语义差别是：前者把所有 Skill 的执行细节塞进了上下文，后者只塞了"目录"。

---

## 五、一次完整的执行流程

用一个真实的例子来看看两种方式的运行差异。

**场景**：Agent 有 4 个 Skill（article-summarizer、docker-deploy、code-review、wespy-fetcher），用户说：

> "帮我总结一下 report.md 这篇文章的核心要点"

**旧方式（饿汉式加载）：**

```
启动时：
  system prompt = 基础指令
                + 4 个 Skill 的完整 SKILL.md 内容（约 1,080 token）
                + Memory

第 1 轮：LLM 决定调用 read("report.md")
第 2 轮：LLM 按 article-summarizer 的格式输出总结

总消耗：1,080 token（4个 Skill 全文）
        其中有效使用：article-summarizer 的 ~250 token
        浪费：830 token（其他 3 个 Skill）
```

**新方式（渐进式披露）：**

```
启动时：
  system prompt = 基础指令
                + 4 个 Skill 的摘要列表（约 80 token）
                + Memory

第 1 轮：LLM 调用 load_skill("article-summarizer")
         ← 返回完整的 250 token SKILL.md 内容

第 2 轮：LLM 调用 read("report.md")

第 3 轮：LLM 按 article-summarizer 的格式输出总结

总消耗：80 token（摘要列表）+ 250 token（按需加载）= 330 token
        全部有效使用
        浪费：0 token
```

代价：多了一轮 LLM 调用（用来 load_skill）。

这是渐进式披露的固有成本：**用一次额外的工具调用，换取大量节省的上下文空间**。在大多数情况下，这个交换是划算的。

---

## 六、什么时候需要渐进式披露

不是所有场景都需要渐进式披露。判断标准很简单：

**需要的场景：**

- Skill 数量超过 10 个，且不是每次任务都会用到全部 Skill
- 有 Skill 内容很长（超过 500 行的详细操作手册）
- 任务类型多样，每次任务通常只用 1-2 个 Skill
- 需要同时跑多个 Agent，节省 token 成本很重要

**不需要的场景：**

- Skill 总数少于 5 个
- 每次任务几乎都会用到全部 Skill（比如一个高度垂直的工作流 Agent）
- Skill 内容都很短（每个 100 token 以内），总量可控
- 对延迟极度敏感，不能接受多一轮 LLM 调用

一个简单的经验公式：

```
如果 (Skill 数量 × 平均 Skill token 数) > 2000 token
→ 考虑引入渐进式披露
```

---

## 七、一张图看清两种方式的差别

```
饿汉式加载（agent-skills-mcp.py）
──────────────────────────────────────────

  Agent 启动
    │
    ▼
  load_skills() ──读取全部 SKILL.md──▶ system prompt
  [Skill A: 全文 250t]                 │
  [Skill B: 全文 300t]                 │（任务开始前已全部加载）
  [Skill C: 全文 350t]                 │
  [Skill D: 全文 180t]                 │
    │                                  ▼
    └────────────────────────────▶ 第 1 轮 LLM 调用
                                     （上下文已含 1080t 的 Skill 内容）


渐进式披露（agent-progressive-skill.py）
──────────────────────────────────────────

  Agent 启动
    │
    ▼
  load_skill_index() ──读取摘要──▶ system prompt
  [Skill A: 一行 20t]              │
  [Skill B: 一行 20t]              │（只有目录，约 80t）
  [Skill C: 一行 20t]              │
  [Skill D: 一行 20t]              │
    │                              ▼
    └──────────────────────▶ 第 1 轮 LLM 调用
                               Agent 决定使用 Skill A
                                 │
                                 ▼
                             load_skill("A") → 返回全文 250t
                                 │
                                 ▼
                             第 2 轮 LLM 调用
                               （此时上下文含 250t 的 Skill A 全文）
```

---

## 结语

渐进式披露解决的不只是"省 token"的问题，它解决的是 **Skill 系统的规模化问题**。

当 Skill 只有几个时，用哪种方式都无所谓。当 Skill 积累到几十上百个时，饿汉式加载变成了一种"税"——每次任务开始，都要先交一大笔上下文税，不管用不用得上。

渐进式披露把这笔税变成了按用付费：只有真正用到某个 Skill 的任务，才加载那个 Skill 的全文。其他任务只支付一行摘要的代价。

**这是同一个道理在不同层面的应用：**

- 第六篇讲的 Compaction：把历史对话压缩成摘要，按需展开
- 本篇讲的 Progressive Skill Disclosure：把 Skill 内容压缩成摘要，按需展开
- Claude Code 的 Deferred Tools：把工具 schema 压缩成名称列表，按需展开

同一个思想——**Context is a limited resource. Defer what you don't need right now.**

---

*本文是「从零开始理解 Agent」系列的番外篇。配套脚本：[agent-progressive-skill.py](./agent-progressive-skill.py)。完整系列：[第一篇](../01-essence/agent-essence.md) → [第二篇](../02-memory/agent-memory.md) → [第三篇：Rules、Skills 与 MCP](../03-skills-mcp/agent-skills-mcp.md)（本文所在章节的主篇）→ [第四篇](../04-subagent/agent-subagent.md)*
