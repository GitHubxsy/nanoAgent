# 从零开始理解 Agent（四）：一次性子智能体，192 行

> **「从零开始理解 Agent」系列**
>
> - [第一篇：底层原理，只有 103 行](./nanoAgent-01-essence.md)
> - [第二篇：记忆与规划](./nanoAgent-02-memory.md)
> - [第三篇：Rules、Skills 与 MCP](./nanoAgent-03-rules-skills-mcp.md)
> - **第四篇：一次性子智能体**（本文）—— 192 行
> - [第五篇：多智能体团队](./nanoAgent-05-teams.md)
> - [第六篇：上下文压缩](./nanoAgent-06-compact.md)
> - [第七篇：安全防线](./nanoAgent-07-safety.md)

---

前三篇我们的 Agent 一直是单线程的——同一个 LLM、同一个 messages 列表、同一个工具集，串行处理所有事情。这种设计简单，但面对复杂任务会暴露一个问题：

**上下文污染。**

想象你让 Agent 同时开发"Python 后端"和"HTML 前端"。如果它在同一个 messages 里混着做，前端的 HTML 代码和后端的 Python 代码会互相干扰，LLM 的注意力被分散，输出质量下降。

解决方案：**SubAgent（子智能体）**——为每个子任务启动独立的 Agent 循环，拥有专属角色和干净的上下文。

对应代码：[`agent-subagent.py`](../agent-subagent.py)（192 行）

---

## 一、核心思路：SubAgent 就是一个工具

这是这篇文章最重要的一个认知：

**SubAgent 不是一个特殊系统，它就是一个工具调用。**

主 Agent 调用 `subagent` 工具，就像调用 `bash` 工具一样。区别是：`bash` 执行的是 shell 命令，`subagent` 启动的是一个完整的 Agent 循环。

```python
def subagent(role, task):
    """启动一个独立的 Agent 循环，拥有专属角色和独立上下文"""

    # 独立的 messages，干净的开始
    sub_messages = [
        {"role": "system", "content": f"You are a {role}. Be concise and focused."},
        {"role": "user", "content": task}
    ]

    # SubAgent 不能再派 subagent（防无限递归）
    sub_tools = [t for t in tools if t["function"]["name"] != "subagent"]

    for _ in range(10):
        response = client.chat.completions.create(
            model=MODEL, messages=sub_messages, tools=sub_tools
        )
        message = response.choices[0].message
        sub_messages.append(message)

        if not message.tool_calls:
            return message.content  # 完成，把结果返回给主 Agent

        # 执行工具，追加结果
        for tc in message.tool_calls:
            ...

    return "SubAgent: max iterations reached"
```

然后把这个函数注册为工具：

```python
tools = [
    ...
    {
        "type": "function",
        "function": {
            "name": "subagent",
            "description": "Delegate a task to a specialized sub-agent with its own role and independent context.",
            "parameters": {
                "type": "object",
                "properties": {
                    "role": {"type": "string", "description": "The sub-agent's specialty"},
                    "task": {"type": "string", "description": "The specific task to delegate"}
                },
                "required": ["role", "task"]
            }
        }
    }
]
```

就这样。主 Agent 现在可以这样工作：

```
主 Agent 收到任务："创建 TODO 应用，包含 Python 后端和 HTML 前端"
    │
    ├──▶ subagent(role="Python backend developer", task="创建 FastAPI 后端...")
    │        └──▶ 独立 Agent 循环（读/写/bash...）
    │        └──▶ 完成，返回结果字符串
    │
    └──▶ subagent(role="Frontend developer", task="创建 HTML 前端...")
             └──▶ 独立 Agent 循环
             └──▶ 完成，返回结果字符串
```

---

## 二、SubAgent 的四个关键特性

### 1. 专属角色（Role）

SubAgent 的 system prompt 是 `You are a {role}`，角色可以是：
- `"Python backend developer"`
- `"DBA specialized in PostgreSQL"`
- `"Security auditor"`

不同角色让 LLM 产生不同的"人格"——后端开发者关注 API 设计，安全审计员关注漏洞，DBA 关注索引优化。

### 2. 独立上下文（Independent Context）

SubAgent 有自己的 `sub_messages` 列表，和主 Agent 完全隔离。前端代码不会出现在后端 Agent 的上下文里，反之亦然。干净的上下文 = 更好的专注度。

### 3. 一次性（Disposable）

SubAgent 完成任务后就消亡，没有记忆，没有状态。下次调用 `subagent` 是一个全新的 Agent，从空白开始。

这和[第五篇的 Teams](./nanoAgent-05-teams.md) 形成对比——Teams 里的 Agent 是持久的，有身份，有记忆。

### 4. 防递归

```python
# SubAgent 不能再派 subagent（防无限递归）
sub_tools = [t for t in tools if t["function"]["name"] != "subagent"]
```

这一行代码防止了 SubAgent 继续派生 SubAgent，避免无限递归导致栈溢出和 API 费用爆炸。

---

## 三、主 Agent vs SubAgent 的分工

```
主 Agent（Orchestrator / 调度者）
  │
  ├── 分析任务，决定哪些部分需要委派
  ├── 自己处理简单、全局性的工作（读整体结构、整合结果）
  └── 通过 subagent 工具委派专业子任务

SubAgent（Executor / 执行者）
  │
  ├── 专注于一个具体任务
  ├── 拥有独立的工具访问权限
  └── 完成后把结果字符串返回给主 Agent
```

主 Agent 的 system prompt 体现了这个设计：

```python
system = "You are an orchestrator agent. You can do tasks yourself OR delegate to specialized sub-agents using the 'subagent' tool. Use subagent when a task benefits from focused expertise."
```

---

## 四、运行效果

```bash
python agent-subagent.py "创建一个 TODO 应用，包含 Python 后端和 HTML 前端"
```

输出示例：

```
[Tool] subagent({"role": "Python backend developer", "task": "..."})
==================================================
[SubAgent:Python backend developer] 开始: ...
==================================================
  [SubAgent:Python backend developer] write({"path": "backend/main.py", ...})
  [SubAgent:Python backend developer] bash({"command": "pip install fastapi"})
[SubAgent:Python backend developer] 完成

[Tool] subagent({"role": "Frontend developer", "task": "..."})
==================================================
[SubAgent:Frontend developer] 开始: ...
==================================================
  [SubAgent:Frontend developer] write({"path": "frontend/index.html", ...})
[SubAgent:Frontend developer] 完成
```

两个 SubAgent 分别在自己的"沙盒"里工作，互不干扰。

---

## 五、SubAgent 的限制：它是临时工

SubAgent 解决了**任务隔离**的问题，但它有一个根本局限：**一次性**。

每次调用 `subagent`，都会启动一个全新的循环，不记得上次做过什么。如果你需要"前端开发者和后端开发者反复协商接口设计"，SubAgent 做不到——因为"前端"下次再被调用时是一个新实例，不记得之前的讨论。

这个问题需要**持久多智能体（Teams）**来解决，这是[第五篇](./nanoAgent-05-teams.md)的主题。

---

*本文基于 [sanbuphy/nanoAgent](https://github.com/sanbuphy/nanoAgent) 项目分析。*
