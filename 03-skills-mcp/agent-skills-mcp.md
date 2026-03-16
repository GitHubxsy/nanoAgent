# 从零开始理解 Agent（三）：OpenClaw / Claude Code 的 Rules、Skills 与 MCP 机制

> **「从零开始理解 Agent」系列** —— 通过一个不到 300 行的开源项目 [nanoAgent](https://github.com/sanbuphy/nanoAgent)，逐层拆解 OpenClaw / Claude Code 等 AI Agent 背后的全部核心概念。
>
> - [第一篇：底层原理，只有 115 行](../01-essence/agent-essence.md) —— 工具 + 循环
> - [第二篇：记忆与规划](../02-memory/agent-memory.md) —— 182 行
> - **第三篇：Rules、Skills 与 MCP**（本文）—— 265 行
> - [第四篇：SubAgent 子智能体](../04-subagent/agent-subagent.md) —— 192 行
> - [第五篇：多智能体协作与编排](../05-teams/agent-teams.md) —— 270 行
> - [第六篇：上下文压缩](../06-compact/agent-compact.md) —— 169 行
> - [第七篇：安全与权限控制](../07-safety/agent-safe.md) —— 219 行

在前两篇中，我们一步步构建了 Agent 的核心能力：[第一篇](../01-essence/agent-essence.md)用 115 行代码搭好了"工具 + 循环"的地基；[第二篇](../02-memory/agent-memory.md)用 67 行增量代码装上了记忆和规划。

但在第二篇结尾，我们留下了三个未解之谜：工具是硬编码的，没有行为约束，规划是被动触发的。

今天我们继续进化—— [agent-skills-mcp.py](https://github.com/sanbuphy/nanoAgent/blob/main/03-skills-mcp/agent-skills-mcp.py)（265 行）。如果你用过 OpenClaw 或 Claude Code，你对 `CLAUDE.md` 规则文件、`.agent/skills/` 技能目录、MCP 工具配置一定不陌生——这些概念正是本篇要拆解的核心。agent-skills-mcp.py 在前两个版本的基础上，引入了四个新概念来回答那三个问题：

| 未解问题 | 解决方案 | 新概念 |
|---------|---------|--------|
| 工具是硬编码的 | 外部配置文件动态加载工具 | **MCP**（Model Context Protocol） |
| 没有行为约束 | 声明式规则文件注入 prompt | **Rules** + **Skills** |
| 规划是被动的 | 把规划注册为 Agent 可自主调用的工具 | **Plan-as-Tool** |

---

## 一、三个版本全景对比

先回顾整个进化路线：

| 能力 | agent-essence.py (115行) | agent-memory.py (182行) | agent-skills-mcp.py (265行) |
|------|---|---|---|
| 基础工具 | bash / read / write | bash / read / write | read / write / **edit** / **glob** / **grep** / bash |
| 记忆 | ❌ | ✅ 文件持久化 | ✅ 文件持久化 |
| 规划 | ❌ | ✅ 外部函数，手动触发 | ✅ **规划本身是一个工具，Agent 自主触发** |
| Rules | ❌ | ❌ | ✅ `.agent/rules/*.md` |
| Skills | ❌ | ❌ | ✅ `.agent/skills/*.json` |
| MCP | ❌ | ❌ | ✅ `.agent/mcp.json` |
| 工具扩展性 | 硬编码 3 个 | 硬编码 3 个 | 基础 7 个 + **MCP 动态加载 N 个** |

---

## 二、更精细的工具集：从"能用"到"好用"

agent-skills-mcp.py 首先在基础工具上做了大幅扩充，从 3 个增加到 7 个：

```python
base_tools = [
    {"name": "read",  "description": "Read file with line numbers", ...},
    {"name": "write", "description": "Write content to file", ...},
    {"name": "edit",  "description": "Replace string in file", ...},   # 新增
    {"name": "glob",  "description": "Find files by pattern", ...},    # 新增
    {"name": "grep",  "description": "Search files for pattern", ...}, # 新增
    {"name": "bash",  "description": "Run shell command", ...},
    {"name": "plan",  "description": "Break down complex task", ...}   # 新增
]
```

新增的工具不是随意选择的——它们恰好对应了 Claude Code 的核心工具集。其中最值得深入分析的是 `edit` 和改进后的 `read`。

### edit：用约束引导 LLM 行为

```python
def edit(path, old_string, new_string):
    try:
        with open(path, 'r') as f:
            content = f.read()
        if content.count(old_string) != 1:
            return f"Error: old_string must appear exactly once"
        new_content = content.replace(old_string, new_string)
        with open(path, 'w') as f:
            f.write(new_content)
        return f"Successfully edited {path}"
    except Exception as e:
        return f"Error: {str(e)}"
```

这个工具有一个精妙的约束：**`old_string` 必须在文件中恰好出现一次**。出现零次说明目标不存在，出现多次则无法确定该替换哪一处。

这个"唯一性约束"迫使 LLM 在调用 `edit` 之前先用 `read` 或 `grep` 确认上下文，大大降低了误编辑的概率。对比第一篇中 agent-essence.py 的 `write_file`（直接覆盖整个文件），`edit` 精确到了字符串级别——这正是 Claude Code 中 `str_replace` 工具的设计思路。

> **设计启示**：用工具的约束来引导 LLM 的行为，比在 prompt 中告诫"小心编辑"可靠得多。约束是硬性的，prompt 是软性的。

### read：行号 + 分页

```python
def read(path, offset=None, limit=None):
    try:
        with open(path, 'r') as f:
            lines = f.readlines()
        start = offset if offset else 0
        end = start + limit if limit else len(lines)
        numbered = [f"{i+1:4d} {line}" for i, line in enumerate(lines[start:end], start)]
        return ''.join(numbered)
    except Exception as e:
        return f"Error: {str(e)}"
```

相比第一篇中简单的 `read_file`，这个版本支持 `offset` 和 `limit` 分页读取，还会给每行加上行号。行号看似微不足道，但对 LLM 配合 `edit` 使用时极其重要——LLM 可以精确定位"第 23 行附近的那段代码"。

---

## 三、Rules：教 Agent "做人的规矩"

### 3.1 加载与注入

```python
RULES_DIR = ".agent/rules"

def load_rules():
    rules = []
    if not os.path.exists(RULES_DIR):
        return ""
    try:
        for rule_file in Path(RULES_DIR).glob("*.md"):
            with open(rule_file, 'r') as f:
                rules.append(f"# {rule_file.stem}\n{f.read()}")
        return "\n\n".join(rules) if rules else ""
    except:
        return ""
```

Rules 是存放在 `.agent/rules/` 目录下的 Markdown 文件。Agent 启动时全部加载，注入到 system prompt 中：

```python
if rules:
    context_parts.append(f"\n# Rules\n{rules}")
```

### 3.2 Rules 是什么、怎么用

你可以创建这样的规则文件：

```markdown
<!-- .agent/rules/code-style.md -->
- 使用 Python 3.10+ 语法
- 所有函数必须有 docstring
- 变量命名使用 snake_case
- 不要使用 print 调试，使用 logging 模块
```

```markdown
<!-- .agent/rules/safety.md -->
- 永远不要执行 rm -rf / 或类似的危险命令
- 修改文件前先备份
- 不要修改 .env 文件中的密钥
```

### 3.3 Rules 的本质

Rules 是**项目级的 system prompt 扩展**。它解决了一个关键问题：不同项目、不同团队、不同场景对 Agent 的要求不同。与其每次在对话中反复叮嘱"记得用 snake_case"，不如写一次规则文件，永久生效。

如果你用过 OpenClaw 或 Claude Code，你一定对 `CLAUDE.md` 不陌生——它就是 Rules 的工程化实现。在 Claude Code 中对应 `CLAUDE.md` 文件和 `.claude/rules/` 目录，在 OpenClaw 中也沿用了相同的约定。在 Cursor 中是 `.cursorrules`，在 GitHub Copilot 中是 `.github/copilot-instructions.md`。名字不同，本质一样——**用声明式文件定制 Agent 的行为边界**。

回顾第二篇中 agent-memory.py 的 system prompt 构建方式，当时只有"基础指令 + 记忆"两层。现在变成了三层拼接：

```
最终 system prompt = 基础指令 + Rules（项目规则） + Skills（技能描述） + Memory（历史记忆）
```

---

## 四、Skills：可插拔的技能注册

### 4.1 加载与注入

```python
SKILLS_DIR = ".agent/skills"

def load_skills():
    skills = []
    if not os.path.exists(SKILLS_DIR):
        return []
    try:
        for skill_file in Path(SKILLS_DIR).glob("*.json"):
            with open(skill_file, 'r') as f:
                skills.append(json.load(f))
        return skills
    except:
        return []
```

Skills 是 `.agent/skills/` 目录下的 JSON 文件，以列表摘要的形式注入 system prompt：

```python
if skills:
    context_parts.append(
        f"\n# Skills\n" + "\n".join(
            [f"- {s['name']}: {s.get('description', '')}" for s in skills]
        )
    )
```

一个 Skill 文件可能长这样：

```json
{
  "name": "docker-deploy",
  "description": "Deploy application using Docker Compose. Steps: 1) Check Dockerfile exists, 2) Run docker-compose build, 3) Run docker-compose up -d, 4) Verify containers are running.",
  "triggers": ["deploy", "docker", "container"]
}
```

> **关于 Skill 的文件格式：** 在 OpenClaw / Claude Code 的实际实现中，Skill 的标准格式是 **Markdown**（每个 Skill 目录下有一个 `SKILL.md`，里面详细描述执行步骤、最佳实践、示例代码等）。但 nanoAgent 原始仓库中采用的是 **JSON** 格式，所以代码里用 `json.load()` 来解析。这不影响理解核心思路——不管是 Markdown 还是 JSON，本质都是"把技能描述加载出来注入到 system prompt"。格式只是载体，思想是一样的。

### 4.2 Skills vs Rules

| 维度 | Rules | Skills |
|------|-------|--------|
| 文件格式 | Markdown | JSON |
| 作用 | 约束行为（"不要做什么"） | 提供能力（"可以怎么做"） |
| 类比 | 公司规章制度 | 员工培训手册 |
| 注入方式 | 全文注入 | 名称 + 描述摘要 |

Rules 管约束，Skills 管能力。一个告诉 Agent "做人的底线"，一个告诉 Agent "做事的方法"。

---

## 五、MCP：让 Agent 拥有无限工具的协议

### 5.1 什么是 MCP？

回忆第一篇中 agent-essence.py 的工具定义方式——直接在代码里硬编码。想加一个新工具？改代码、重新部署。这在生产环境中完全不可接受。

MCP（Model Context Protocol）是 Anthropic 提出的一个开放标准，它定义了 LLM 与外部工具之间的通信协议。你可以把 MCP 理解为"AI 世界的 USB 接口"——任何遵循这个协议的工具服务都可以即插即用地接入 Agent。

如果你用过 OpenClaw 或 Claude Code，你一定在配置文件里见过 `mcpServers` 这个字段——配置一个 GitHub MCP Server，Agent 就能直接操作 PR 和 Issue；配置一个数据库 MCP Server，Agent 就能执行 SQL 查询。这就是 MCP 的威力。

### 5.2 agent-skills-mcp.py 中的 MCP 实现

```python
MCP_CONFIG = ".agent/mcp.json"

def load_mcp_tools():
    if not os.path.exists(MCP_CONFIG):
        return []
    try:
        with open(MCP_CONFIG, 'r') as f:
            config = json.load(f)
        mcp_tools = []
        for server_name, server_config in config.get("mcpServers", {}).items():
            if server_config.get("disabled", False):
                continue
            for tool in server_config.get("tools", []):
                mcp_tools.append({"type": "function", "function": tool})
        return mcp_tools
    except:
        return []
```

配置文件 `.agent/mcp.json`：

```json
{
  "mcpServers": {
    "filesystem": {
      "disabled": false,
      "tools": [{
        "name": "list_directory",
        "description": "List contents of a directory with metadata",
        "parameters": {
          "type": "object",
          "properties": {"path": {"type": "string"}},
          "required": ["path"]
        }
      }]
    },
    "database": {
      "disabled": true,
      "tools": [...]
    }
  }
}
```

### 5.3 MCP 的精髓：一行代码

```python
all_tools = base_tools + mcp_tools
```

这一行是整个 MCP 集成的精髓。MCP 加载的工具和基础工具使用完全相同的 JSON Schema 格式，直接拼接成一个列表传给 LLM。LLM 完全不需要知道某个工具是"内置的"还是"MCP 加载的"——对它来说，工具就是工具。

### 5.4 nanoAgent 简化了什么

需要说明的是，nanoAgent 的 MCP 实现是高度简化的——它只实现了"工具注册"（把 schema 加载给 LLM），没有实现"工具执行"（通过网络调用远程 MCP Server）。实际调用时会走到 else 分支返回 "Tool not implemented"：

| 特性 | 真实 MCP | nanoAgent 的实现 |
|------|----------|-----------------|
| 工具发现 | 运行时从 MCP Server 动态查询 | 从 JSON 文件静态读取 |
| 工具执行 | 通过 stdio/HTTP 调用远程 Server | ⚠️ 未实现 |
| 传输协议 | stdio / SSE / Streamable HTTP | 无 |

虽然不完整，但它展示了 MCP 集成的核心思路：**工具定义与工具实现的分离**。在完整实现中，那个 else 分支会变成一个 MCP 客户端调用。

### 5.5 MCP 解决的根本问题

```
没有 MCP 的世界:                    有 MCP 的世界:

Agent A         Agent B             MCP Server: Slack  MCP Server: GitHub
├── Slack (自写) ├── Slack (自写)         │                │
├── GitHub(自写) ├── Jira (自写)          └───── 标准协议 ──┘
└── DB (自写)    └── DB (自写)                    │
                                         ┌───────┼───────┐
每个 Agent 各写各的                      Agent A  Agent B  Agent C
N × M 的工作量                          工具实现一次，全部共享
                                         N + M 的工作量
```

---

## 六、Plan-as-Tool：规划从"被动触发"到"自主决策"

### 6.1 进化路径回顾

三个版本中，规划经历了清晰的进化：

| 版本 | 规划方式 | 谁来决定是否规划 |
|------|---------|----------------|
| agent-essence.py | 无规划 | — |
| agent-memory.py | `create_plan()` 外部函数 | **用户**（手动加 `--plan`） |
| agent-skills-mcp.py | `plan` 注册为工具 | **LLM 自己** |

在 agent-skills-mcp.py 中，`plan` 出现在工具列表里：

```python
{"name": "plan", "description": "Break down complex task into steps and execute sequentially", ...}
```

这意味着 LLM 遇到复杂任务时可以**主动调用** `plan` 工具进行拆解，无需用户干预。

### 6.2 递归执行与防无限循环

`plan` 工具的执行逻辑是整个文件最复杂的部分：

```python
if function_name == "plan":
    plan_mode = True
    function_response = available_functions[function_name](**function_args)
    messages.append({"role": "tool", "tool_call_id": tool_call.id, "content": function_response})

    if current_plan:
        results = []
        for i, step in enumerate(current_plan, 1):
            messages.append({"role": "user", "content": step})
            result, messages = run_agent_step(
                messages,
                [t for t in tools if t["function"]["name"] != "plan"]  # 关键：排除 plan
            )
            results.append(result)
        plan_mode = False
        current_plan = []
        return "\n".join(results), messages
```

三个关键设计：

**递归调用 `run_agent_step`。** Plan 生成的每个步骤都通过 `run_agent_step` 执行，每步内部仍然可以使用 read、write、bash 等工具。这形成了一个两层循环——外层是规划步骤，内层是每步的 ReAct 循环。

**排除 plan 工具本身。** 执行步骤时的工具列表中刻意去掉了 `plan`，配合 `plan_mode` 全局变量双重保护，防止"在规划中再次规划"的无限递归。

**上下文跨步共享。** 和第二篇中一样，`messages` 在所有步骤间共享。

```
用户: "重构项目的测试框架"
  │
  ▼
LLM 判断任务复杂 → 主动调用 plan 工具
  │
  ▼
plan() 返回 4 个步骤
  │
  ├── Step 1: 分析当前测试结构
  │     └── run_agent_step() → [glob, read, grep]
  │
  ├── Step 2: 创建新的测试目录
  │     └── run_agent_step() → [bash, write]
  │
  ├── Step 3: 迁移现有测试文件
  │     └── run_agent_step() → [read, edit, write]
  │
  └── Step 4: 验证所有测试通过
        └── run_agent_step() → [bash]
```

---

## 七、全部模块如何组装在一起

```python
def run_agent_claudecode(task, use_plan=False):
    print("[Init] Loading ClaudeCode features...")

    # 1. 从文件系统加载所有外部配置
    memory = load_memory()        # 历史记忆
    rules = load_rules()          # 行为规则
    skills = load_skills()        # 技能注册
    mcp_tools = load_mcp_tools()  # MCP 外部工具

    # 2. 合并工具列表（基础工具 + MCP 工具）
    all_tools = base_tools + mcp_tools

    # 3. 构建 system prompt（基础指令 + Rules + Skills + Memory）
    context_parts = ["You are a helpful assistant..."]
    if rules:   context_parts.append(f"\n# Rules\n{rules}")
    if skills:  context_parts.append(f"\n# Skills\n...")
    if memory:  context_parts.append(f"\n# Previous Context\n{memory}")

    messages = [{"role": "system", "content": "\n".join(context_parts)}]
    # 4. 执行 ...
```

```
┌─────────────────────── 文件系统 ───────────────────────┐
│                                                         │
│  .agent/rules/*.md    → load_rules()    → system prompt │
│  .agent/skills/*.json → load_skills()   → system prompt │
│  .agent/mcp.json      → load_mcp_tools()→ tools 列表    │
│  agent_memory.md      → load_memory()   → system prompt │
│                                                         │
└─────────────────────────────────────────────────────────┘
                          │
                          ▼
              ┌──── Agent 运行时 ────┐
              │                      │
              │  system prompt =     │
              │    基础指令           │
              │    + Rules           │
              │    + Skills          │
              │    + Memory          │
              │                      │
              │  tools =             │
              │    base_tools (7个)   │
              │    + mcp_tools (N个)  │
              │                      │
              └──────────────────────┘
```

这个架构揭示了一个重要原则：**Agent 的能力由两个正交维度定义**——

- **prompt 维度**（知道什么）：Rules、Skills、Memory 扩展的是 LLM 的认知
- **tools 维度**（能做什么）：MCP 扩展的是 LLM 的行动能力

两者独立变化、自由组合，构成了 Agent 的完整能力空间。

---

## 八、从 115 行到 265 行的认知地图

三篇文章读下来，我们在 265 行代码里看到了 Agent 的全部核心概念。用一张七层架构图来做最后的回顾：

```
┌───────────────────────────────────────────────────────┐
│                    Agent 架构全景                       │
│                                                        │
│  ┌──────────────┐  第三篇：agent-skills-mcp.py         │
│  │  Rules       │  行为约束层 ──── .agent/rules/       │
│  │  Skills      │  技能知识层 ──── .agent/skills/      │
│  │  MCP         │  工具扩展层 ──── .agent/mcp.json     │
│  │  Plan Tool   │  自主规划层 ──── plan() 作为工具      │
│  ├──────────────┤  第二篇：agent-memory.py               │
│  │  Memory      │  持久记忆层 ──── agent_memory.md     │
│  │  Planning    │  任务分解层 ──── create_plan()       │
│  │  Multi-step  │  多步编排层 ──── 步骤间上下文共享     │
│  ├──────────────┤  第一篇：agent-essence.py                    │
│  │  LLM         │  推理决策层 ──── OpenAI API          │
│  │  Tools       │  工具执行层 ──── bash/read/write     │
│  │  Loop        │  核心循环层 ──── for + tool_calls    │
│  └──────────────┘                                      │
└───────────────────────────────────────────────────────┘
```

每一层都在回答一个关键问题：

| 层 | 回答的问题 | 引入篇 |
|----|-----------|--------|
| Loop | Agent 如何自主运行？ | 第一篇 |
| Tools | Agent 如何作用于世界？ | 第一篇 |
| Memory | Agent 如何记住过去？ | 第二篇 |
| Planning | Agent 如何应对复杂任务？ | 第二篇 |
| Rules | Agent 如何遵守约束？ | 第三篇 |
| Skills | Agent 如何获得领域知识？ | 第三篇 |
| MCP | Agent 如何获得新工具？ | 第三篇 |

这七层架构，就是当今所有主流 Agent 框架（OpenClaw、Claude Code、Cursor Agent、Devin、OpenHands 等）的共同骨架。nanoAgent 用不到 300 行 Python 代码，把这个骨架完整地呈现了出来。

---

## 九、结语

| 文件 | 行数 | 核心主题 | 一句话总结 |
|------|------|---------|-----------|
| agent-essence.py | 115 | 工具 + 循环 | Agent 的最小本质 |
| agent-memory.py | 182 | 记忆 + 规划 | Agent 的时间维度——记住过去、规划未来 |
| agent-skills-mcp.py | 265 | Rules + Skills + MCP | Agent 的空间维度——扩展知识与工具 |

如果你跟着这三篇文章走了下来，你已经理解了 Agent 最核心的架构要素。但还有一个问题我们没有触及：当任务复杂到一个 Agent 忙不过来时怎么办？能不能让 Agent 自己找帮手？

这就是多智能体协作——SubAgent 的领域。在 [第四篇：SubAgent 子智能体](../04-subagent/agent-subagent.md) 中，我们将用不到 30 行新增代码，让主 Agent 学会"分工派活"。

> *"The question is not what you look at, but what you see."* — Henry David Thoreau
>
> nanoAgent README 的这句引言，放在这里再合适不过。看过这 265 行代码之后，当你再打开 OpenClaw、Claude Code、Cursor 或任何 Agent 产品时，你看到的不再是"魔法"，而是——一个循环、几个工具、一段记忆、一份规则。

---

*本文基于 [sanbuphy/nanoAgent](https://github.com/sanbuphy/nanoAgent) 的 agent-skills-mcp.py 分析。完整系列：[第一篇：底层原理](../01-essence/agent-essence.md) → [第二篇：记忆与规划](../02-memory/agent-memory.md) → 第三篇：Rules、Skills 与 MCP（本文） → [第四篇：SubAgent 子智能体](../04-subagent/agent-subagent.md)*
