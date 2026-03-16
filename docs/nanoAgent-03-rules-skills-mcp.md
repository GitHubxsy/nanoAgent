# 从零开始理解 Agent（三）：Rules、Skills 与 MCP，282 行

> **「从零开始理解 Agent」系列**
>
> - [第一篇：底层原理，只有 103 行](./nanoAgent-01-essence.md)
> - [第二篇：记忆与规划](./nanoAgent-02-memory.md)
> - **第三篇：Rules、Skills 与 MCP**（本文）—— 282 行
> - [第四篇：SubAgent](./nanoAgent-04-subagent.md)
> - [第五篇：多智能体团队](./nanoAgent-05-teams.md)
> - [第六篇：上下文压缩](./nanoAgent-06-compact.md)
> - [第七篇：安全防线](./nanoAgent-07-safety.md)

---

前两篇解决了"Agent 能干活"和"Agent 有记忆"的问题。但工具还是硬编码的，行为也完全不受约束。这一篇引入三个 Claude Code / Cursor 都在用的核心设计：

1. **Rules**：告诉 Agent 该做什么、不该做什么
2. **Skills**：可复用的行为模板，不用每次重新描述
3. **MCP（Model Context Protocol）**：不改代码就能扩展工具

对应代码：[`agent-claudecode.py`](../agent-claudecode.py)（282 行）

---

## 一、Rules：给 Agent 立规矩

### 问题所在

第一篇的 Agent 有一个潜在危险：它可以执行 `rm -rf /`，没有任何东西阻止它。更普遍的问题是，每次用 Agent 处理特定项目时，你都要在 prompt 里反复说明规范——"用 Python 3.10 以上的语法"、"不要修改 tests/ 目录"……

**Rules 是把这些规范从 prompt 里抽出来，存到文件里，自动加载。**

### 实现方式

```
.agent/
  rules/
    coding-style.md    # "使用 Python 3.10+ 语法，遵循 PEP 8"
    safety.md          # "不要删除任何文件，修改前必须备份"
    project-context.md # "这是一个 FastAPI 项目，入口是 main.py"
```

```python
RULES_DIR = ".agent/rules"

def load_rules():
    rules = []
    for rule_file in Path(RULES_DIR).glob("*.md"):
        with open(rule_file, 'r') as f:
            rules.append(f"# {rule_file.stem}\n{f.read()}")
    return "\n\n".join(rules)
```

加载后注入 system prompt：

```python
rules = load_rules()
if rules:
    context_parts.append(f"\n# Rules\n{rules}")
```

**Rules 的本质：把你想反复说的话，写成文件，自动注入 system prompt。** Agent 每次启动都会"读到"这些规矩。

---

## 二、Skills：可复用的行为模板

### 问题所在

假设你每次都要让 Agent "先运行测试，把失败的测试输出整理成 Markdown 报告"——这是一个固定的工作流，你不想每次都手打一遍描述。

**Skills 是把这种固定工作流打包成 JSON，让 Agent 按模板执行。**

### 实现方式

```
.agent/
  skills/
    run-tests.json
    code-review.json
```

`run-tests.json` 示例：
```json
{
  "name": "run-tests",
  "description": "运行项目测试并生成报告",
  "steps": [
    "运行 pytest，收集所有失败用例",
    "将失败信息整理成 Markdown 表格，写入 test-report.md",
    "输出摘要：通过 N 个，失败 M 个"
  ]
}
```

```python
SKILLS_DIR = ".agent/skills"

def load_skills():
    skills = []
    for skill_file in Path(SKILLS_DIR).glob("*.json"):
        with open(skill_file, 'r') as f:
            skills.append(json.load(f))
    return skills
```

Skills 加载后注入 system prompt，Agent 就"知道"有哪些预定义的工作流可以直接引用。

---

## 三、MCP：不改代码就能接入新工具

### 什么是 MCP？

MCP（Model Context Protocol）是 Anthropic 提出的开放协议，定义了 LLM 与外部工具服务之间的通信标准。简单说：**MCP 让你在不修改 Agent 代码的情况下，接入任意第三方工具**。

想接入数据库查询工具？配置一下，不改代码。想接入 GitHub API？配置一下，不改代码。这就是 MCP 的价值。

### 实现方式

```
.agent/
  mcp.json
```

`mcp.json` 示例：
```json
{
  "mcpServers": {
    "github": {
      "tools": [
        {
          "name": "github_search",
          "description": "Search GitHub repositories",
          "parameters": {
            "type": "object",
            "properties": {
              "query": {"type": "string"}
            },
            "required": ["query"]
          }
        }
      ]
    }
  }
}
```

```python
MCP_CONFIG = ".agent/mcp.json"

def load_mcp_tools():
    with open(MCP_CONFIG, 'r') as f:
        config = json.load(f)
        mcp_tools = []
        for server_name, server_config in config.get("mcpServers", {}).items():
            if server_config.get("disabled", False):
                continue
            for tool in server_config.get("tools", []):
                mcp_tools.append({"type": "function", "function": tool})
        return mcp_tools

# 把 MCP 工具和内置工具合并
all_tools = base_tools + mcp_tools
```

**MCP 的本质：动态扩展工具列表，而不需要修改 Agent 代码。** 工具的配置在 JSON 文件里，Agent 启动时自动加载。

---

## 四、三者的层次关系

```
┌──────────────────────────────────────────┐
│              System Prompt               │
│                                          │
│  ┌──────────┐  ┌──────────┐  ┌────────┐ │
│  │  Rules   │  │  Skills  │  │ Memory │ │
│  │ (约束)   │  │ (模板)   │  │ (历史) │ │
│  └──────────┘  └──────────┘  └────────┘ │
└──────────────────────────────────────────┘
              ▼
┌──────────────────────────────────────────┐
│              Tool List                   │
│                                          │
│  ┌──────────────┐  ┌────────────────┐   │
│  │  Base Tools  │  │   MCP Tools    │   │
│  │ (内置工具)   │  │  (动态加载)    │   │
│  └──────────────┘  └────────────────┘   │
└──────────────────────────────────────────┘
```

- **Rules / Skills / Memory** → 影响 Agent 的"思维方式"（注入 system prompt）
- **MCP Tools** → 影响 Agent 的"行动能力"（扩展工具列表）

---

## 五、工具集升级：从 3 个到 7 个

这一版同时升级了内置工具，从第一篇的 3 个增加到 7 个，更接近真实 Coding Agent 的工具集：

| 工具 | 说明 | 对应能力 |
|------|------|----------|
| `read` | 带行号读取文件（支持分页） | 精确定位代码 |
| `write` | 写入文件 | 创建新文件 |
| `edit` | 精准字符串替换 | 局部修改（不是整文件覆盖） |
| `glob` | 按模式查找文件 | 文件系统探索 |
| `grep` | 在文件中搜索模式 | 代码搜索 |
| `bash` | 执行 shell 命令 | 运行脚本/测试 |
| `plan` | 任务分解并顺序执行 | 复杂任务规划 |

---

## 六、动手试一试

```bash
# 创建 rules 和 skills 目录
mkdir -p .agent/rules .agent/skills

# 写一条规则
echo "不要删除任何文件。修改代码前，先用 read 工具阅读目标文件。" > .agent/rules/safety.md

# 运行 agent
python agent-claudecode.py "找出 agent.py 中最长的函数并解释它的作用"
python agent-claudecode.py --plan "重构 agent.py，将工具定义和工具实现分离到不同模块"
```

---

## 七、下一步

这一篇的 Agent 已经很强了——有记忆、有规则、工具可扩展。但它还是单线程的，一次只能做一件事。

复杂任务（比如"同时开发前端和后端"）需要**并行**执行多个子任务。这就是[第四篇：SubAgent](./nanoAgent-04-subagent.md) 要解决的问题。

---

*本文基于 [sanbuphy/nanoAgent](https://github.com/sanbuphy/nanoAgent) 项目分析。*
