# 技术分享：从零开始理解 Agent

> **nanoAgent 系列** —— 7 篇正文 + 1 篇番外，逐层拆解 OpenClaw / Claude Code 等 AI Agent 背后的全部核心概念。
>
> 项目地址：[GitHubxsy/nanoAgent](https://github.com/GitHubxsy/nanoAgent)

---

## 一、为什么要读这个系列？

很多人用过 ChatGPT、Claude，也听说过"AI Agent"。但 Agent 到底和普通对话有什么区别？Claude Code、Cursor Agent 这类工具的底层是什么？

这个系列的答案是：**用代码说话**。

| 普通对话（Chat） | Agent |
|---|---|
| 一问一答，用户驱动 | 自主循环，目标驱动 |
| 只能生成文本 | 可以调用工具，作用于真实世界 |
| 用户提问 → 模型回答 | 用户下达任务 → 思考 → 调用工具 → 观察 → 继续思考 → 返回答案 |

**一句话总结：Agent = LLM + 工具 + 循环**

---

## 二、系列全览

| # | 文章 | 代码行数 | 核心主题 |
|---|------|---------|---------|
| 01 | 底层原理，只有 100 行 | 103 行 | 工具 + 循环（Agent 的最小本质） |
| 02 | 记忆与规划 | 206 行 | 持久记忆 + Plan-then-Execute |
| 03 | Rules、Skills 与 MCP | 282 行 | 行为约束 + 技能注册 + 工具协议 |
| 04 | SubAgent 子智能体 | 192 行 | 一次性委派，分工干活 |
| 05 | 多智能体团队协作 | 270 行 | 持久身份 + 通信通道 + 生命周期 |
| 06 | 上下文压缩 | 169 行 | 对抗 context window 上限 |
| 07 | 三道安全防线 | 219 行 | 黑名单 + 用户确认 + Hook 管道 |
| 番外 | Harness 到底是什么？ | — | Agent = Model + Harness |

---

## 三、第一篇：底层原理，只有 100 行

**核心公式：Agent = LLM + 工具 + 循环**

### 架构分层

```
┌────────────────────────────────────────┐
│  1. LLM 客户端初始化                    │
├────────────────────────────────────────┤
│  2. 工具定义（Tool Schema，JSON 说明书） │
├────────────────────────────────────────┤
│  3. 工具实现（Python 函数）              │
├────────────────────────────────────────┤
│  4. Agent 循环（Core Loop）             │
└────────────────────────────────────────┘
```

### 三个工具

| 工具名 | 能力 | 危险等级 |
|--------|------|----------|
| `execute_bash` | 执行任意 shell 命令 | ⚠️ 极高 |
| `read_file` | 读取文件内容 | 中 |
| `write_file` | 写入文件 | 高 |

### 核心循环（最精华的 20 行）

```python
def run_agent(user_message, max_iterations=5):
    messages = [system_prompt, user_message]

    for _ in range(max_iterations):
        response = client.chat.completions.create(
            model=model, messages=messages, tools=tools
        )
        message = response.choices[0].message
        messages.append(message)

        if not message.tool_calls:        # 没有工具调用 → 任务完成
            return message.content

        for tool_call in message.tool_calls:  # 有工具调用 → 执行并追加结果
            result = available_functions[tool_call.function.name](**args)
            messages.append({"role": "tool", "content": result})

    return "Max iterations reached"
```

### 关键洞察

> **LLM 本身不会执行任何代码。** 它只是输出一段结构化 JSON，表达"我想调用 execute_bash，参数是 ls -la"。真正的执行发生在我们的 Python 代码里。
>
> **LLM 是大脑，代码是手脚。**

### 运行时序示例

```
用户: "统计 Python 文件数，写入 count.txt"

第 1 轮 → LLM 返回 tool_call: execute_bash("find . -name '*.py' | wc -l")
       → 代码执行，得到 "42"，追加到 messages

第 2 轮 → LLM 看到结果，返回 tool_call: write_file("count.txt", "42")
       → 代码执行，写入文件

第 3 轮 → LLM 判断任务完成，返回纯文本 → 退出循环
```

---

## 四、第二篇：记忆与规划

### 新增能力对比

| 能力 | 第一篇 (100行) | 第二篇 (182行) |
|------|------|------|
| 跨会话记忆 | ❌ 每次运行都失忆 | ✅ `agent_memory.md` 文件持久化 |
| 任务规划 | ❌ 走一步看一步 | ✅ 先拆解再执行 |
| 多步串联 | ❌ | ✅ 步骤间共享 `messages` 上下文 |

### 记忆的本质

```
写入：任务完成后 → save_memory() → 追加到 agent_memory.md
读取：下次启动时 → load_memory() → 只取最后 50 行（滑动窗口）
注入：拼接到 system prompt → "Previous context: ..."
```

> **LLM 本身没有持久记忆。** 所有"记忆"都是把外部存储的信息搬运到 prompt 中。

### 两种记忆类型

| 类型 | 载体 | 生命周期 |
|------|------|----------|
| 短期记忆 | `messages` 列表 | 单次运行内，步骤间共享 |
| 长期记忆 | `agent_memory.md` 文件 | 跨多次运行 |

### 两种规划范式

```
ReAct（第一篇）            Plan-then-Execute（第二篇）

思考 → 行动 → 观察         先规划（全局思考）
  ↑         │                    │
  └─────────┘           步骤1 → 步骤2 → 步骤3
                         (每步内部仍是 ReAct)
```

---

## 五、第三篇：Rules、Skills 与 MCP

### 三个问题的解决方案

| 问题 | 解决方案 | 概念 |
|------|---------|------|
| 工具是硬编码的 | 外部配置文件动态加载 | **MCP** |
| 没有行为约束 | 声明式规则文件注入 prompt | **Rules** |
| 想扩展 Agent 的领域知识 | 技能文件注入 prompt | **Skills** |
| 规划是被动触发的 | 把规划注册为工具 | **Plan-as-Tool** |

### System Prompt 的组装公式

```
最终 system prompt = 基础指令 + Rules（项目规则）+ Skills（技能描述）+ Memory（历史记忆）
```

### Rules vs Skills

| | Rules | Skills |
|--|-------|--------|
| 文件格式 | Markdown | JSON |
| 作用 | 约束行为（不要做什么） | 提供能力（可以怎么做） |
| 类比 | 公司规章制度 | 员工培训手册 |

> **你一定见过的 Rules：** OpenClaw/Claude Code 的 `CLAUDE.md`、Cursor 的 `.cursorrules`、GitHub Copilot 的 `.github/copilot-instructions.md` —— 名字不同，本质一样。

### MCP：AI 世界的 USB 接口

```python
mcp_tools = load_mcp_tools()   # 从配置文件动态加载
all_tools = base_tools + mcp_tools  # 一行代码搞定合并
```

MCP（Model Context Protocol）解决的核心问题：

```
没有 MCP：每个 Agent 各写各的工具，N×M 的工作量
有  MCP：工具实现一次，所有 Agent 共享，N+M 的工作量
```

### 能力的两个正交维度

```
prompt 维度（知道什么）：Rules + Skills + Memory
tools  维度（能做什么）：base_tools + MCP tools
```

---

## 六、第四篇：SubAgent 子智能体

### 核心思想

> 主 Agent 当项目经理，把子任务委派给拥有不同专业身份的 SubAgent，各管一块，互不干扰。

### SubAgent 的生命周期

```
生成 → 接收任务 → 干活（可以调用工具）→ 返回结果摘要 → 消亡
```

**一次性的。** 没有持久身份，没有跨调用的记忆。

### 实现只需 ~30 行

```python
def subagent(role, task):
    sub_messages = [
        {"role": "system", "content": f"You are a {role}. Be concise and focused."},
        {"role": "user", "content": task}
    ]
    # 排除 subagent 自身，防止无限递归
    sub_tools = [t for t in tools if t["function"]["name"] != "subagent"]

    for _ in range(10):
        response = client.chat.completions.create(model=MODEL, messages=sub_messages, tools=sub_tools)
        message = response.choices[0].message
        sub_messages.append(message)
        if not message.tool_calls:
            return message.content
        for tc in message.tool_calls:
            result = available_functions[tc.function.name](**json.loads(tc.function.arguments))
            sub_messages.append({"role": "tool", "tool_call_id": tc.id, "content": result})
    return "SubAgent: max iterations reached"
```

### 关键设计决策

1. **独立的 messages** —— SubAgent 只知道自己的角色和任务，不被主 Agent 的历史干扰
2. **不同的 system prompt** —— 同一个 LLM，不同角色描述，展现不同专业行为
3. **排除 subagent 工具自身** —— 防止无限递归

### Plan vs SubAgent

| | Plan（第二篇） | SubAgent（第四篇） |
|--|---|---|
| 上下文 | 所有步骤共享 messages | 每个 SubAgent 独立 messages |
| 身份 | 同一个角色 | 不同专业角色 |
| 生命周期 | 步骤间持续存在 | 用完即消亡 |
| 适合场景 | 步骤之间有依赖 | 子任务相对独立 |

---

## 七、第五篇：多智能体团队协作

### 为什么需要 Teams？SubAgent 的局限

第四篇的 SubAgent 已经能分工，但有三个根本缺陷：

```
问题 1: SubAgent 没有记忆
  主 Agent 调用 subagent("dev", "写后端") → 完成
  主 Agent 再调用 subagent("dev", "优化后端") → 已经忘记之前写了什么

问题 2: SubAgent 没有身份
  每次调用都是一个全新的角色，没有积累，没有上下文

问题 3: SubAgent 之间无法通信
  前端写完了，后端不知道 API 接口是什么
  只能通过主 Agent 中转，信息损耗严重
```

**Teams 的解答：给每个 Agent 三样东西 —— 持久记忆、固定身份、通信通道。**

---

### 从临时工到正式员工

| | SubAgent（临时工） | Teams Agent（正式员工） |
|--|--|--|
| 有名字吗？ | ❌ | ✅ 有固定名字和角色 |
| 记得上次做了什么？ | ❌ 每次失忆 | ✅ messages 跨轮次累积 |
| 能收到同事消息吗？ | ❌ | ✅ inbox 收件箱 |
| 什么时候消失？ | 函数返回即消亡 | team.disband() 才消失 |
| 适合什么场景？ | 独立子任务，一次性 | 有依赖、需协作的长任务 |

---

### 三大核心能力

```
能力 1: 持久记忆（Persistent Memory）
  → Agent.messages 是一个列表，每次 chat() 都往里追加
  → 第二次调用时，Agent 还记得第一次做了什么

能力 2: 身份与生命周期（Identity & Lifecycle）
  → hire()：Agent 被创建，身份确立
  → chat()：Agent 可被多次调用，记忆持续累积
  → disband()：团队解散，所有 Agent 生命周期结束

能力 3: 通信通道（Communication Channel）
  → send(from, to, msg)：点对点消息
  → broadcast(from, msg)：广播给所有人
  → Agent.inbox：收件箱，下次 chat() 时自动注入
```

---

### 核心实现：Agent 类

```python
class Agent:
    def __init__(self, name, role):
        self.name = name
        self.role = role
        self.inbox = []          # 通信通道：收件箱
        self.messages = [        # 持久记忆：所有对话历史
            {"role": "system", "content": f"You are {name}, a {role}."}
        ]

    def receive(self, sender, message):
        """其他 Agent 发来消息 → 放进收件箱"""
        self.inbox.append({"from": sender, "content": message})

    def chat(self, task):
        # 1. 先消化 inbox 里积压的消息
        if self.inbox:
            mail = "\n".join(f"[来自 {m['from']}]: {m['content']}" for m in self.inbox)
            self.messages.append({"role": "user", "content": f"你收到了团队成员的消息:\n{mail}"})
            resp = client.chat.completions.create(model=MODEL, messages=self.messages)
            self.messages.append(resp.choices[0].message)
            self.inbox.clear()

        # 2. 执行本次任务（messages 是持续累积的，Agent 记得之前所有对话）
        self.messages.append({"role": "user", "content": task})
        for _ in range(10):
            response = client.chat.completions.create(
                model=MODEL, messages=self.messages, tools=tools
            )
            message = response.choices[0].message
            self.messages.append(message)                    # ← 记忆累积

            if not message.tool_calls:
                return message.content

            for tc in message.tool_calls:
                result = available_functions[tc.function.name](**args)
                self.messages.append({"role": "tool", "content": result})  # ← 工具结果也进记忆
```

**关键：`self.messages` 永远不清空**（SubAgent 的 messages 是局部变量，函数返回即销毁）

---

### 核心实现：Team 类

```python
class Team:
    def __init__(self):
        self.agents = {}       # name → Agent 对象

    def hire(self, name, role):
        """招募：创建 Agent，存入字典"""
        agent = Agent(name, role)
        self.agents[name] = agent
        return agent

    def send(self, from_name, to_name, message):
        """点对点：只投递给指定成员的 inbox"""
        self.agents[to_name].receive(from_name, message)

    def broadcast(self, from_name, message):
        """广播：投递给除自己以外的所有成员"""
        for name, agent in self.agents.items():
            if name != from_name:
                agent.receive(from_name, message)

    def disband(self):
        """解散：清空 agents 字典，所有 Agent 对象释放"""
        self.agents.clear()
```

---

### 四阶段协作流程

```
第 1 阶段：PM 规划团队（LLM 根据任务自动决定需要哪些角色）
  ┌─────────────────────────────────────┐
  │ 任务：创建 TODO 应用                  │
  │ 规划结果：                           │
  │   alice — backend developer         │
  │   bob   — frontend developer        │
  │   carol — reviewer                  │
  └─────────────────────────────────────┘

第 2 阶段：招募（hire）
  team.hire("alice", "backend developer")
  team.hire("bob",   "frontend developer")
  team.hire("carol", "reviewer")

第 3 阶段：协作开发（逐个 chat，完成后广播成果）
  alice.chat("写 Flask TODO API")
    → 创建 app.py
    → broadcast: "我完成了后端 API，接口在 /todos"

  bob.chat("写 HTML 前端")    ← bob 的 inbox 已有 alice 的广播
    → 先消化 inbox（知道了 API 地址）
    → 创建 index.html（直接对接正确的 API）
    → broadcast: "前端完成"

  carol.chat("最终审查")      ← carol 的 inbox 有所有人的广播
    → 先消化 inbox（了解全局进展）
    → 做 code review，输出审查报告

第 4 阶段：解散
  team.disband()
```

---

### 通信机制详解

```
点对点（send）              广播（broadcast）
─────────────────          ──────────────────────────────
alice → bob               alice → [bob, carol, dave, ...]
  仅 bob 的 inbox          所有人的 inbox（除 alice 自己）
  适合：传递特定信息         适合：同步全局进展
```

**消息在什么时候被处理？**

```
agent.receive()  →  消息进入 inbox（只是存储，不立即处理）
agent.chat()     →  先看 inbox，消化后再执行新任务
                    → 这样 Agent 能在执行任务前，先了解团队最新动态
```

---

### 持久记忆的真实价值

```python
# SubAgent：每次调用完全独立，无记忆
subagent("dev", "写后端")   # messages 是局部变量，返回后消失
subagent("dev", "写单测")   # 完全不知道之前写了什么后端

# Teams Agent：记忆累积
alice.chat("写后端")         # alice.messages 增长到 20 条
alice.chat("给后端写单测")   # alice.messages 已有 20 条上下文
                             # → 知道文件结构、变量名、边界条件
```

> **一句话：持久记忆让 Agent 不只是"执行者"，而是真正"理解项目"的团队成员。**

---

### 生命周期时序图

```
时间轴 →

alice:  [hire]──[chat:写后端]──────[broadcast]──[chat:修bug]──[disband]
                                       │
bob:    [hire]──────────────[inbox]──[chat:写前端]──[broadcast]──[disband]
                                                        │
carol:  [hire]──────────────────────────────[inbox]──[chat:审查]──[disband]

                            ↑ 信息在这里流动，每个 Agent 的记忆独立累积
```

---

### 关键设计决策

| 设计 | 原因 |
|------|------|
| `messages` 永不清空 | 持久记忆的根本；清空 = SubAgent |
| `inbox` 在 `chat()` 开头消化 | 保证 Agent 在执行任务前已获得最新信息 |
| LLM 自动规划团队成员 | 不同任务需要不同角色，让模型决定比写死更灵活 |
| 最后一个成员固定为 reviewer | 审查需要全局视野，inbox 收到了所有广播 |
| `disband()` 不销毁历史 | Python GC 自动处理；如需保存，序列化 `messages` 即可 |

---

### Teams vs SubAgent vs Plan 三者对比

| 维度 | Plan（第二篇） | SubAgent（第四篇） | Teams（第五篇） |
|------|-----------|---------------|------------|
| 上下文共享 | 所有步骤共享同一个 messages | 每个 SubAgent 独立 messages | 每个 Agent 独立，但通过 inbox 通信 |
| 身份 | 单一角色贯穿全程 | 临时角色，用完即弃 | 固定身份，多次交互 |
| 适合场景 | 步骤有严格依赖顺序 | 子任务相对独立 | 需要协作且有知识积累的复杂任务 |
| 通信方式 | 无（步骤间靠共享 messages） | 无（靠主 Agent 中转） | send + broadcast |
| 代码复杂度 | 低 | 中 | 高（但值得） |

---

## 八、第六篇：上下文压缩

### 问题：messages 会无限增长

```
每轮循环 messages += [LLM回复, 工具返回结果]
→ 读几个大文件 + 几次 grep
→ 很快撑爆 context window
→ API 报错：context_length_exceeded
→ Agent 挂了，任务半途而废
```

### 解决方案：Compaction（压缩）

```
压缩前：
  [system][user][tool×15][assistant×15]  ← 越来越长

压缩后：
  [system][摘要（旧消息的精华）][最近 N 条保持原样]
              ↑
         用 LLM 自己来总结自己的历史
```

```python
def compact_messages(messages, keep_recent=6, threshold=20):
    if len(messages) <= threshold:
        return messages  # 不需要压缩

    system = [m for m in messages if m["role"] == "system"]
    recent = messages[-keep_recent:]
    to_compress = messages[len(system):-keep_recent]

    summary = llm.call(f"Summarize: {to_compress}")  # 让 LLM 来压缩
    summary_msg = {"role": "assistant", "content": f"[Summary] {summary}"}

    return system + [summary_msg] + recent
```

> **本质：** 不是让模型处理更长的文本，而是让 Harness 确保模型始终看到最重要的信息。

---

## 九、第七篇：三道安全防线

### 背景

第一篇的 `execute_bash` 可以执行任意 shell 命令——包括 `rm -rf /`。LLM 不理解后果，只知道"这是删除文件的工具"。

### 三道防线

```
LLM 输出一条命令
  │
  ▼
防线 1: 命令黑名单
  │  "rm -rf /"  → 🚫 直接拦截
  │  "ls -la"    → ✅ 通过
  ▼
防线 2: 用户确认
  │  "这个命令安全吗？[y/N]"
  │  用户说 N   → 🚫 拒绝执行
  │  用户说 y   → ✅ 通过
  ▼
防线 3: 输出截断
  │  结果超过 5000 字符 → 截断，防止撑爆 context
  ▼
真正执行
```

### Hook 管道架构

```python
before_hooks = [check_blacklist, ask_confirmation]
after_hooks  = [truncate_output]

def execute_with_hooks(tool_name, args, func):
    for hook in before_hooks:        # 执行前拦截
        blocked, msg = hook(tool_name, args)
        if blocked: return msg
    result = func(**args)            # 实际执行
    for hook in after_hooks:         # 执行后处理
        result = hook(tool_name, result)
    return result
```

> **Hook 管道** = 可插拔的执行管道，压缩、续写、lint 检查、安全拦截，都可以注入其中。这正是 Claude Code 权限系统的核心设计。

---

## 十、番外篇：Harness 是什么？

### 关键词演变

| 年代 | 关键词 | 关注点 |
|------|--------|--------|
| 2023-2024 | Prompt Engineering | 怎么跟模型说话 |
| 2025 | Context Engineering | 怎么组织上下文 |
| 2026 | Harness Engineering | 怎么搭建模型周围的整套系统 |

### 核心论点

> **Agent = Model + Harness**

- **Model**：提供智能（思考、决策）
- **Harness**：提供让智能真正能干活的一切基础设施

> "Harness" 在英文中是"马具"的意思——套在马身上让它能拉车干活的那一整套装备。

### 七篇文章 = Harness 的核心骨架

| Harness 组件 | 对应系列文章 |
|-------------|------------|
| 工具 + 执行循环 | 第一篇 |
| 记忆 + 规划 | 第二篇 |
| System Prompt + Rules + Skills + MCP | 第三篇 |
| 子 Agent 生成 | 第四篇 |
| 多 Agent 编排 | 第五篇 |
| 上下文压缩 / Compaction | 第六篇 |
| 安全防线 + 执行 Hook | 第七篇 |

### 一张图看清 Model vs Harness

```
┌─────────────────────────────────────────────────────┐
│                    Harness                            │
│                                                       │
│  Rules / Skills / MCP Tools                          │
│         ↓                                            │
│  System Prompt + 工具列表                             │
│  Memory（第二篇）+ Compaction（第六篇）               │
│         ↓                                            │
│      ┌─────────┐                                     │
│      │  Model  │  ← 模型只管思考和决策                │
│      └─────────┘                                     │
│         ↓                                            │
│  Hook 管道（第七篇）：黑名单 → 用户确认 → 执行        │
│         ↓                                            │
│  工具执行层（第一篇）：bash / read / write            │
│         ↓                                            │
│  协作层（第四、五篇）：SubAgent / Teams               │
└─────────────────────────────────────────────────────┘
```

### 为什么 Harness 概念重要？

**1. 它重新定义了"谁在决定 Agent 的好坏"**

同一个模型，配上好的 Harness 和差的 Harness，产出质量天壤之别。Claude Code 和普通 Agent 用的模型大家都能调用——差别在 Harness，不在 Model。

**2. 它告诉你应该把精力花在哪**

- 你写的 `CLAUDE.md` → Harness 的一部分
- 你配的 MCP Server → Harness 的一部分
- 你写的 Skill → Harness 的一部分
- 你做的安全检查 → Harness 的一部分

**3. 你已经是 Harness 工程师了**

读完这七篇，你已经亲手搭过 Harness 的完整核心骨架，只是之前没有这个名字。

```
Agent = Model + Harness
      = Model + 你写的那 507 行代码
```

---

## 十一、架构演进全景

```
┌──────────────────────────────────────────────────────────┐
│                    Agent 完整架构                          │
│                                                           │
│  ┌──────────────┐  第七篇：agent-safe.py                  │
│  │  安全防线     │  黑名单 + 用户确认 + 输出截断 + Hook     │
│  ├──────────────┤  第六篇：agent-compact.py               │
│  │  上下文压缩   │  Compaction，对抗 context window 上限   │
│  ├──────────────┤  第五篇：agent-teams.py                 │
│  │  Teams       │  持久身份 + 通信通道 + 生命周期管理       │
│  ├──────────────┤  第四篇：agent-subagent.py              │
│  │  SubAgent    │  一次性委派，独立上下文，分工干活          │
│  ├──────────────┤  第三篇：agent-skills-mcp.py            │
│  │  Rules       │  行为约束层 → .agent/rules/             │
│  │  Skills      │  技能知识层 → .agent/skills/            │
│  │  MCP         │  工具扩展层 → .agent/mcp.json           │
│  ├──────────────┤  第二篇：agent-memory.py                │
│  │  Memory      │  持久记忆层 → agent_memory.md           │
│  │  Planning    │  任务分解层 → Plan-then-Execute          │
│  ├──────────────┤  第一篇：agent-essence.py               │
│  │  LLM         │  推理决策层 → OpenAI API                │
│  │  Tools       │  工具执行层 → bash / read / write       │
│  │  Loop        │  核心循环层 → for + tool_calls          │
│  └──────────────┘                                         │
└──────────────────────────────────────────────────────────┘
```

| 篇 | 核心主题 | 一句话总结 |
|----|---------|-----------|
| 一 | 工具 + 循环 | LLM 是大脑，代码是手脚 |
| 二 | 记忆 + 规划 | 时间维度——记住过去，规划未来 |
| 三 | Rules + Skills + MCP | 空间维度——扩展知识与工具 |
| 四 | SubAgent | 协作维度——给 Agent 找临时帮手 |
| 五 | Teams | 团队维度——持久身份与通信协作 |
| 六 | 上下文压缩 | 健壮性——对抗 context window 上限 |
| 七 | 安全防线 | 安全性——三道防线保护真实世界 |
| 番外 | Harness | Agent = Model + 你搭的那套系统 |

---

## 十二、动手试一试

```bash
git clone https://github.com/GitHubxsy/nanoAgent.git
cd nanoAgent
pip install -r requirements.txt

export OPENAI_API_KEY="your-key"
export OPENAI_BASE_URL="https://api.openai.com/v1"

# 第一篇：感受最基础的 Agent 循环
python 01-essence/agent-essence.py "统计当前目录下有多少个 Python 文件"

# 第二篇：体验记忆与规划
python 02-memory/agent-memory.py --plan "找到所有 TODO 注释并整理到 todo.md"

# 第四篇：体验 SubAgent 分工
python 04-subagent/agent-subagent.py "创建一个 TODO 应用，包含 Python 后端和 HTML 前端"

# 第七篇：体验安全防线（尝试执行危险命令会被拦截）
python 07-safety/agent-safe.py "删除所有临时文件"
```

---

*「从零开始理解 Agent」系列 —— 7 篇文章，7 个代码文件，1 篇番外，从 100 行到 507 行，逐层拆解 Agent 的完整架构。*
