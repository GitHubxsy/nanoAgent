# 从零开始理解 Agent（五）：从临时工到正式团队——多智能体协作与编排

> **「从零开始理解 Agent」系列** —— 从一个极简开源项目 [nanoAgent](https://github.com/sanbuphy/nanoAgent) 出发，逐层拆解 OpenClaw / Claude Code 等 AI Agent 背后的全部核心概念。
>
> - [第一篇：底层原理，只有 115 行](../01-essence/agent-essence.md) —— 工具 + 循环
> - [第二篇：记忆与规划](../02-memory/agent-memory.md) —— 182 行
> - [第三篇：Rules、Skills 与 MCP](../03-skills-mcp/agent-skills-mcp.md) —— 265 行
> - [第四篇：SubAgent 子智能体](../04-subagent/agent-subagent.md) —— 192 行
> - **第五篇：多智能体协作与编排**（本文）—— 270 行
> - [第六篇：上下文压缩](../06-compact/agent-compact.md) —— 169 行
> - [第七篇：安全与权限控制](../07-safety/agent-safe.md) —— 219 行

上一篇我们实现了 SubAgent——主 Agent 可以临时派出一个"专家"来干活。但我们也明确定义了 SubAgent 的本质：**一次性临时工，生成 → 干活 → 返回摘要 → 消亡，没有身份，没有记忆。**

这在很多场景下够用了。但想想现实中的软件开发团队：后端工程师写完 API 后，前端工程师需要知道接口长什么样；测试工程师发现 bug 后，需要告诉开发去修；开发修完后，测试还得再验一遍——**同一个人，被多次找到，而且他还记得上次做了什么。**

SubAgent 做不到这些。每次调用都是一个全新的、失忆的临时工。

那怎么办？答案是：**从临时工升级为正式团队。**

> **关于本篇代码的说明：**
>
> 和第四篇一样，本篇的 `agent-teams.py` 是我们**新开发的文件**（[GitHub 源码](https://github.com/GitHubxsy/nanoAgent/blob/main/05-teams/agent-teams.py)），不在 nanoAgent 原始仓库中。它在 `agent-subagent.py` 的基础上，用两个类（`Agent` + `Team`）实现了多智能体团队协作。

---

## 一、临时工 vs 正式员工：差什么？

| | SubAgent（临时工） | Teams Agent（正式员工） |
|--|--|--|
| 有名字吗？ | ❌ 只有一个临时角色描述 | ✅ 有名字（alice）、有固定角色 |
| 记得上次做了什么吗？ | ❌ 每次调用都失忆 | ✅ 多次交互之间记忆持续累积 |
| 能收到同事消息吗？ | ❌ 互相看不到 | ✅ 有收件箱，能收消息 |
| 什么时候消失？ | 函数返回就没了 | 团队解散才消失 |

要从临时工升级为正式团队，需要补齐三样东西：

**1. 能跨多轮对话存活的持久智能体** —— Agent 有记忆，被多次 `chat()` 调用时记得之前做过什么，不会像 SubAgent 那样每次都失忆

**2. 身份与生命周期管理** —— Agent 有名字、有角色，被创建（入职）、持续存活（干活）、最终解散（离职），而不是用完即弃

**3. 智能体之间的通信通道** —— Agent 之间可以互相发消息（点对点或广播），而不是彼此隔离、互相看不到

接下来看代码怎么实现。

---

## 二、核心实现：两个类搞定一切

整个 `agent-teams.py` 只有 270 行，核心新增是两个类：`Agent` 和 `Team`。工具层（read/write/edit/bash）和 Agent 循环完全复用前几篇的代码。

### 2.1 Agent 类：有状态的持久智能体

先回忆 SubAgent 的实现——一个函数：

```python
# SubAgent（第四篇）—— 一个函数，用完就没
def subagent(role, task):
    sub_messages = [...]  # 局部变量，函数返回即消亡
    for _ in range(10):
        ...
    return result  # 返回后 sub_messages 被垃圾回收，一切归零
```

现在看 Teams 中的 Agent——一个类：

```python
class Agent:
    def __init__(self, name, role):
        self.name = name                # 身份：有名字
        self.role = role                # 身份：有角色
        self.inbox = []                 # 通信：收件箱
        self.messages = [               # 记忆：持久保持
            {"role": "system", "content": f"You are {name}, a {role}. Be concise and focused."}
        ]
```

区别只有一个，但意义巨大：**`messages` 从函数的局部变量变成了对象的实例属性**。

局部变量在函数返回后就被垃圾回收。实例属性只要对象还活着，就一直在。这意味着你可以对同一个 Agent 多次调用 `chat()`，每次的对话历史都会累积在 `self.messages` 中——**Agent 记得之前做过什么**。

### 2.2 chat() 方法：带收件箱的 Agent 循环

```python
def chat(self, task):
    # 第 1 步：如果 inbox 有新消息，先读取并消化
    if self.inbox:
        mail = "\n".join(f"[来自 {m['from']}]: {m['content']}" for m in self.inbox)
        self.messages.append({"role": "user", "content": f"你收到了团队成员的消息:\n{mail}"})
        resp = client.chat.completions.create(model=MODEL, messages=self.messages)
        self.messages.append(resp.choices[0].message)
        self.inbox.clear()

    # 第 2 步：执行本次任务（和之前的 Agent 循环一样）
    self.messages.append({"role": "user", "content": task})
    for _ in range(10):
        response = client.chat.completions.create(model=MODEL, messages=self.messages, tools=tools)
        message = response.choices[0].message
        self.messages.append(message)
        if not message.tool_calls:
            return message.content
        for tc in message.tool_calls:
            # ... 执行工具，追加结果（和第一篇完全一样）
```

关键在第 1 步：每次 `chat()` 开始前，Agent 会先检查收件箱。如果有其他 Agent 发来的消息，就先读取、消化（让 LLM 处理一下），然后清空收件箱。这样 Agent 在执行任务时，已经知道了队友们的最新进展。

### 2.3 receive() 方法：通信通道

```python
def receive(self, sender, message):
    self.inbox.append({"from": sender, "content": message})
```

就这一行。往收件箱里追加一条消息。简单到不需要解释。

---

## 三、Team 类：生命周期管理与通信编排

```python
class Team:
    def __init__(self):
        self.agents = {}  # name → Agent

    def hire(self, name, role):
        """招募：创建一个持久 Agent"""
        agent = Agent(name, role)
        self.agents[name] = agent
        return agent

    def send(self, from_name, to_name, message):
        """点对点通信"""
        self.agents[to_name].receive(from_name, message)

    def broadcast(self, from_name, message):
        """广播：给团队所有其他人发消息"""
        for name, agent in self.agents.items():
            if name != from_name:
                agent.receive(from_name, message)

    def disband(self):
        """解散：所有 Agent 生命周期结束"""
        self.agents.clear()
```

四个方法，对应团队协作的四个动作：

| 方法 | 作用 | 类比 |
|------|------|------|
| `hire()` | 创建 Agent，加入团队 | 招人入职 |
| `send()` | A 给 B 发消息 | 工作群里 @ 某人 |
| `broadcast()` | A 给所有人发消息 | 群发公告 |
| `disband()` | 解散团队，所有 Agent 消亡 | 项目结束，团队解散 |

---

## 四、完整协作流程

```python
def run_team(task):
    team = Team()

    # 第 1 阶段：组建团队
    members = plan_team(task)  # LLM 自动拆分角色
    for m in members:
        team.hire(m["name"], m["role"])

    # 第 2 阶段：逐个执行，每人干完广播成果
    for m in members:
        agent = team.agents[m["name"]]
        result = agent.chat(m["task"])
        team.broadcast(m["name"], f"我完成了任务。摘要: {result[:200]}")

    # 第 3 阶段：最后一个成员做二次审查
    reviewer = team.agents[members[-1]["name"]]
    review = reviewer.chat("请根据团队成果做最终审查")

    # 第 4 阶段：解散
    team.disband()
```

用一个具体例子来说明。假设输入 "创建一个 TODO 应用，包含 Python 后端和 HTML 前端"：

```
[PM] 分析任务，组建团队...
[团队] 3 人:
  1. alice — backend developer → 用 FastAPI 创建 TODO 后端 API
  2. bob — frontend developer → 创建 HTML 前端页面
  3. carol — test engineer → 验证前后端能正常工作

============================================================
  第 1 阶段: 招募团队
============================================================
  [创建] alice (backend developer)
  [创建] bob (frontend developer)
  [创建] carol (test engineer)

============================================================
  第 2 阶段: 协作开发
============================================================

── [1/3] alice 开始工作 ──
  [alice] write({"path": "app.py", ...})
  [alice] → 已创建 app.py，包含 GET/POST/DELETE 三个接口...
  [广播] alice → 全体: 我完成了任务。摘要: 已创建 app.py...

── [2/3] bob 开始工作 ──
  （bob 的 inbox 里有 alice 的广播，他知道后端接口长什么样）
  [bob] write({"path": "index.html", ...})
  [bob] → 已创建 index.html，调用了 alice 定义的 API 接口...
  [广播] bob → 全体: 我完成了任务。摘要: 已创建 index.html...

── [3/3] carol 开始工作 ──
  （carol 的 inbox 里有 alice 和 bob 的广播）
  [carol] read({"path": "app.py"})
  [carol] read({"path": "index.html"})
  [carol] bash({"command": "python -c 'import app; print(\"OK\")'"})
  [carol] → 后端代码语法正确，前端页面已创建，接口调用地址匹配...
  [广播] carol → 全体: 我完成了任务。摘要: 验证通过...

============================================================
  第 3 阶段: carol 做最终审查
============================================================
  （carol 被第二次调用 chat()，她还记得第一次测试的结果）
  [carol] → 最终审查：后端 app.py 包含 3 个接口（GET/POST/DELETE），
            前端 index.html 已正确引用后端地址，代码验证通过，可以交付。
```

注意 **carol 被调用了两次 `chat()`** ：第一次做测试，第二次做审查。第二次时她还记得第一次做了什么——这就是"持久记忆"的价值。SubAgent 做不到这一点，因为每次调用都是一个全新的、失忆的函数。

---

## 五、三大核心能力的代码对照

回到开头提出的三个要求，逐一对照：

### 能力 1：能跨多轮对话存活的持久智能体

```python
# SubAgent：局部变量，函数返回即消亡
def subagent(role, task):
    sub_messages = [...]  # 🔴 生命周期 = 这个函数调用
    ...
    return result         # sub_messages 被回收

# Teams Agent：实例属性，对象存活就一直在
class Agent:
    def __init__(self, ...):
        self.messages = [...]  # 🟢 生命周期 = Agent 对象的生命周期

    def chat(self, task):
        self.messages.append(...)  # 每次调用都往同一个列表里追加
        ...
        # 第 1 次 chat()：messages = [system, user1, assistant1]
        # 第 2 次 chat()：messages = [system, user1, assistant1, user2, assistant2]
        # Agent 在第 2 次时能看到第 1 次的全部历史
```

### 能力 2：身份与生命周期管理

```python
team = Team()

# 入职：Agent 被创建，开始存活
alice = team.hire("alice", "backend developer")
bob   = team.hire("bob",   "frontend developer")

# 存活期间：可以多次交互
alice.chat("创建后端 API")
alice.chat("添加认证中间件")   # alice 记得第一次创建的 API

# 解散：所有 Agent 生命周期结束
team.disband()                 # alice、bob 都消亡了
```

### 能力 3：智能体之间的通信通道

```python
# 点对点：alice 告诉 bob 接口格式
team.send("alice", "bob", "API 接口: GET /todos, POST /todos")

# 广播：alice 告诉所有人
team.broadcast("alice", "后端已完成，接口文档见 API.md")

# bob 下次 chat() 时，会先读 inbox 中的消息
bob.chat("创建前端页面")  # bob 已经知道了 API 接口格式
```

---

## 六、SubAgent vs Teams：什么时候用哪个？

| 场景 | 选 SubAgent | 选 Teams |
|------|------------|----------|
| 子任务之间完全独立 | ✅ 互不干扰，简单直接 | 没必要，杀鸡用牛刀 |
| 后续任务依赖前面的结果 | ❌ 看不到别人做了什么 | ✅ 通过通信通道传递信息 |
| 需要同一个人多次返工 | ❌ 每次都是新人，不记得 | ✅ 持久记忆，记得上次做了什么 |
| 需要测试 → 修 bug → 再测试 | ❌ 做不到 | ✅ 测试人员和开发都能被多次调用 |

一句话总结：**任务简单、互不相关用 SubAgent；需要协作、需要记忆用 Teams。**

---

## 七、系列总结

五篇文章，从一个 115 行的极简 Agent 出发，逐层叠加能力：

| 篇 | 核心新增 | 一句话 |
|----|---------|--------|
| 一 | 工具 + 循环 | Agent 的最小本质 |
| 二 | 记忆 + 规划 | 记住过去，规划未来 |
| 三 | Rules + Skills + MCP | 扩展知识与工具 |
| 四 | SubAgent | 一次性临时工 |
| **五** | **Agent 类 + Team 类** | **有记忆、有身份、能通信的正式团队** |

从第四篇的 `subagent()` 函数到第五篇的 `Agent` 类，变化只有一个：**`messages` 从局部变量变成了实例属性**。但这一个变化，让 Agent 从"用完即弃的临时工"进化为了"有记忆、有身份、能协作的团队成员"。

这就是软件工程中最朴素的道理：**数据放在哪里，决定了它的生命周期；生命周期决定了能力边界。**

但能力越强，副作用也越大——Agent 干的活越多、协作越复杂，`messages` 就越长。长到撑爆 LLM 的 context window 怎么办？在 [第六篇：上下文压缩](../06-compact/agent-compact.md) 中，我们用一个 30 行的函数来解决这个"自我窒息"问题。

---

*本文基于 agent-teams.py（[GitHub 源码](https://github.com/GitHubxsy/nanoAgent/blob/main/05-teams/agent-teams.py)）分析。完整系列：[第一篇](../01-essence/agent-essence.md) → [第二篇](../02-memory/agent-memory.md) → [第三篇](../03-skills-mcp/agent-skills-mcp.md) → [第四篇](../04-subagent/agent-subagent.md) → 第五篇（本文） → [第六篇](../06-compact/agent-compact.md)*
