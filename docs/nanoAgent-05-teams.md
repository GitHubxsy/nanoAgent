# 从零开始理解 Agent（五）：持久多智能体团队，270 行

> **「从零开始理解 Agent」系列**
>
> - [第一篇：底层原理，只有 103 行](./nanoAgent-01-essence.md)
> - [第二篇：记忆与规划](./nanoAgent-02-memory.md)
> - [第三篇：Rules、Skills 与 MCP](./nanoAgent-03-rules-skills-mcp.md)
> - [第四篇：一次性子智能体](./nanoAgent-04-subagent.md)
> - **第五篇：持久多智能体团队**（本文）—— 270 行
> - [第六篇：上下文压缩](./nanoAgent-06-compact.md)
> - [第七篇：安全防线](./nanoAgent-07-safety.md)

---

[第四篇](./nanoAgent-04-subagent.md)的 SubAgent 是"临时工"——用完即弃，没有身份，没有记忆。

但真实的团队协作不是这样的。前端开发者和后端开发者需要**反复沟通**接口设计；测试工程师需要**记住**哪些功能已经测过；架构师需要**跨轮次**维护整体视图。

这就是 Teams 要解决的问题：**让多个 Agent 拥有持久身份、持久记忆，并且能够互相通信。**

对应代码：[`agent-teams.py`](../agent-teams.py)（270 行）

---

## 一、SubAgent vs Teams：三点核心区别

| 维度 | SubAgent（第四篇） | Teams（本篇） |
|------|---------------------|----------------|
| 生命周期 | 一次性，用完即弃 | 持久，可多次交互 |
| 身份 | 匿名，每次是新实例 | 有名字，有 Agent ID |
| 记忆 | 无 | 有（独立的 messages 历史） |
| 通信 | 无（只返回字符串） | 有（可以互发消息） |

---

## 二、Teams 需要三样东西

### 1. 持久 Agent（Persistent Agent）

Agent 被创建后会一直存在，有自己的 messages 历史，多次调用之间保持上下文。

```python
agents = {}  # {agent_id: {"role": ..., "messages": [...]}}

def create_agent(agent_id, role):
    """创建一个持久 Agent"""
    agents[agent_id] = {
        "role": role,
        "messages": [
            {"role": "system", "content": f"You are {agent_id}, a {role}. ..."}
        ]
    }
    return f"Agent {agent_id} ({role}) created"

def chat_with_agent(agent_id, message):
    """和持久 Agent 对话，它记得之前的所有对话"""
    agent = agents[agent_id]
    agent["messages"].append({"role": "user", "content": message})

    # 执行 Agent 循环，追加到同一个 messages 列表
    result = run_agent_loop(agent["messages"])
    return result
```

关键区别：每次 `chat_with_agent` 都是在**同一个 messages 列表**上追加，不是从头开始。这就是"持久"的含义。

### 2. 消息广播（Message Board）

团队成员需要共享信息。`agent-teams.py` 用一个简单的"公告板"实现：

```python
message_board = []  # 所有 Agent 共享的消息列表

def post_message(from_agent, to_agent, content):
    """Agent 发消息给另一个 Agent（或广播）"""
    message_board.append({
        "from": from_agent,
        "to": to_agent,
        "content": content,
        "timestamp": datetime.now().isoformat()
    })
    return f"Message posted to {to_agent}"

def read_messages(agent_id):
    """读取发给某个 Agent 的消息"""
    msgs = [m for m in message_board if m["to"] in (agent_id, "all")]
    return json.dumps(msgs, ensure_ascii=False, indent=2) if msgs else "No messages"
```

### 3. 调度者（Orchestrator）

主 Agent 负责决定"谁做什么"，创建 Agent、分配任务、协调通信：

```python
# 主 Agent 的工具集包含：
# - create_agent: 创建新团队成员
# - chat_with_agent: 和某个成员对话
# - post_message: 发消息
# - read_messages: 读消息
# - list_agents: 列出所有成员
# + 基础工具（read/write/bash 等）
```

---

## 三、运行时序

以"创建 TODO 应用"为例：

```
主 Agent 收到任务
    │
    ├─▶ create_agent("backend", "Python backend developer")
    ├─▶ create_agent("frontend", "Frontend developer")
    ├─▶ create_agent("tester", "QA engineer")
    │
    ├─▶ chat_with_agent("backend", "设计并实现 REST API，包含 CRUD 接口")
    │       └─▶ backend Agent 循环（写 Python 代码，有自己的 messages 历史）
    │       └─▶ post_message("backend", "frontend", "API 文档：POST /todos, GET /todos/{id}...")
    │
    ├─▶ chat_with_agent("frontend", "读取后端发来的 API 文档，实现 HTML 前端")
    │       └─▶ frontend Agent：read_messages("frontend") → 看到后端的 API 文档
    │       └─▶ frontend Agent 循环（写 HTML/JS）
    │
    ├─▶ chat_with_agent("tester", "测试后端 API 和前端页面")
    │       └─▶ tester Agent 循环（运行测试，报告结果）
    │
    └─▶ 汇总结果，返回给用户
```

---

## 四、持久记忆的体现

假设中途发现 bug，调度者再次 `chat_with_agent("backend", "修复 POST /todos 返回 500 的问题")`：

- `backend` Agent 的 messages 里**已经有**之前的所有上下文（它写了什么代码、做了什么决定）
- 它不需要重新"了解项目"，直接基于历史上下文定位问题

这就是"持久"带来的价值：**Team 成员之间的合作是有上下文的，不是每次都从零开始。**

---

## 五、与 SubAgent 的对比示例

**SubAgent 方式（临时工）：**
```python
# 每次调用都是全新的 Agent
subagent("backend developer", "修复 POST /todos 的 bug")
# ↑ 这个 "backend developer" 不知道之前写了什么代码
```

**Teams 方式（持久团队）：**
```python
# 和同一个 Agent 继续对话
chat_with_agent("backend", "修复 POST /todos 的 bug")
# ↑ backend Agent 记得之前写的所有代码，直接基于上下文修复
```

---

## 六、动手试一试

```bash
python agent-teams.py "创建一个 TODO 应用，包含 Python 后端和 HTML 前端"
```

观察输出中的团队协作过程：
- `[Tool] create_agent(...)` — 团队成员被创建
- `[Tool] chat_with_agent(...)` — 调度者分配任务
- `[SubAgent:backend] write(...)` — 成员在自己的上下文里工作
- `[Tool] post_message(...)` — 成员之间传递信息

---

## 七、Teams 的代价

持久 Agent 带来能力提升，也带来新的挑战：

1. **内存消耗**：每个 Agent 维护独立的 messages 列表，长时间运行后会很大
2. **Context 爆炸**：和 SubAgent 相比，每个 Agent 的 context 会持续增长

这引出了[第六篇](./nanoAgent-06-compact.md)的主题：**当 messages 太长时，如何自动压缩，避免 context window 溢出？**

---

*本文基于 [sanbuphy/nanoAgent](https://github.com/sanbuphy/nanoAgent) 项目分析。*
