# 从零开始理解 Agent（二）：OpenClaw / Claude Code 如何实现记忆与规划

> **「从零开始理解 Agent」系列** —— 通过一个不到 300 行的开源项目 [nanoAgent](https://github.com/sanbuphy/nanoAgent)，逐层拆解 OpenClaw / Claude Code 等 AI Agent 背后的全部核心概念。
>
> - [第一篇：底层原理，只有 115 行](./nanoAgent-01-essence.md) —— 工具 + 循环
> - **第二篇：记忆与规划**（本文）—— 182 行
> - [第三篇：Rules、Skills 与 MCP](./nanoAgent-03-skills-mcp.md) —— 265 行
> - [第四篇：SubAgent 子智能体](./nanoAgent-04-subagent.md) —— 192 行
> - [第五篇：多智能体协作与编排](./nanoAgent-05-teams.md) —— 270 行
> - [第六篇：上下文压缩](./nanoAgent-06-compact.md) —— 169 行
> - [第七篇：安全与权限控制](./nanoAgent-07-safe.md) —— 219 行

上一篇我们用 115 行代码理解了 Agent 的核心公式：**LLM + 工具 + 循环**。但在结尾我们也指出了它的致命缺陷——没有记忆、不会规划。

如果你用过 OpenClaw 或 Claude Code，你会发现它们可以在一个长对话中持续记住之前的操作，面对复杂需求时也会先制定计划再逐步执行。这些能力不是"魔法"，而是可以用很少的代码实现的架构设计。

今天我们看 nanoAgent 的第二个版本 [agent-plus.py](https://github.com/sanbuphy/nanoAgent/blob/main/agent-plus.py)（182 行），它只多了 67 行代码，却解决了两个根本问题：**让 Agent 记住过去**，**让 Agent 规划未来**。

---

## 一、从 agent.py 到 agent-plus.py：多了什么？

| 能力 | agent.py (115 行) | agent-plus.py (182 行) |
|------|----------|---------------|
| 工具调用 | ✅ 3 个工具 | ✅ 3 个工具（不变） |
| 单任务执行 | ✅ | ✅ |
| **跨会话记忆** | ❌ 每次运行都失忆 | ✅ `agent_memory.md` 文件持久化 |
| **任务规划** | ❌ 走一步看一步 | ✅ `create_plan()` 先拆解再执行 |
| **多步串联** | ❌ | ✅ 步骤间共享 `messages` 上下文 |

工具层完全没变——新增的 67 行全部用来构建更高层的能力。这恰好印证了第一篇的结论：工具 + 循环只是地基，记忆和规划才是让 Agent 真正可用的关键。

---

## 二、记忆系统：最朴素但最本质的方案

### 2.1 记忆的存储：一个 Markdown 文件

```python
MEMORY_FILE = "agent_memory.md"

def save_memory(task, result):
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    entry = f"\n## {timestamp}\n**Task:** {task}\n**Result:** {result}\n"
    try:
        with open(MEMORY_FILE, 'a') as f:
            f.write(entry)
    except:
        pass
```

agent-plus.py 用了一种极其朴素的方案——把历史任务和结果追加写入一个 Markdown 文件。没有数据库，没有向量索引，就是纯文本。每次任务执行完毕，Agent 把"什么时间、做了什么、得到什么结果"追加到文件末尾：

```markdown
## 2026-03-12 14:30:00
**Task:** 统计当前目录下的 Python 文件数量
**Result:** 当前目录下共有 42 个 Python 文件。

## 2026-03-12 15:00:00
**Task:** 创建一个 hello.py
**Result:** 已创建 hello.py，内容为打印 Hello World。
```

### 2.2 记忆的加载：滑动窗口

```python
def load_memory():
    if not os.path.exists(MEMORY_FILE):
        return ""
    try:
        with open(MEMORY_FILE, 'r') as f:
            content = f.read()
        lines = content.split('\n')
        return '\n'.join(lines[-50:]) if len(lines) > 50 else content
    except:
        return ""
```

加载记忆时有一个关键细节：**只取最后 50 行**。这是一个简单的滑动窗口策略——记忆文件可能无限增长，但 LLM 的 context window 是有限的。必须截断。

### 2.3 记忆的注入：塞进 System Prompt

```python
def run_agent_plus(task, use_plan=False):
    memory = load_memory()
    system_prompt = "You are a helpful assistant that can interact with the system. Be concise."
    if memory:
        system_prompt += f"\n\nPrevious context:\n{memory}"
    messages = [{"role": "system", "content": system_prompt}]
```

加载出来的记忆被拼接到 system prompt 末尾，以 "Previous context" 的形式注入。LLM 在处理新任务时能"看到"之前的历史。

### 2.4 记忆流程全景

```
第 1 次运行                          第 2 次运行
───────────                        ───────────
用户: "创建 hello.py"               用户: "读取 hello.py 并加上注释"
        │                                  │
        ▼                                  ▼
  system prompt:                    system prompt:
  "You are a helpful               "You are a helpful
   assistant..."                    assistant...
                                    
                                    Previous context:
                                    ## 2026-03-12 14:30
                                    Task: 创建 hello.py
                                    Result: 已创建..."
        │                                  │
        ▼                                  ▼
  Agent 执行任务                     Agent 执行任务
        │                           (知道之前创建过 hello.py)
        ▼                                  │
  save_memory() ──写入──▶ agent_memory.md ◀─── save_memory()
```

### 2.5 记忆的本质

这个方案虽然原始，但揭示了一个根本原理：**LLM 本身没有持久记忆，所有"记忆"都是通过在 prompt 中注入历史信息来实现的。**

无论是 Claude 的 Memory、ChatGPT 的记忆功能，还是更复杂的 RAG 系统，底层都遵循这个模式——只是在"存在哪、怎么找、搬多少"上做得更精细。我们会在文末讨论这些进化方向。

---

## 三、规划系统：让 Agent 学会"先想再做"

### 3.1 为什么需要规划？

回忆第一篇中 agent.py 的工作方式：把整个任务丢给 LLM，让它在循环中自行摸索。简单任务没问题，但面对复杂任务（比如"重构整个项目的目录结构"），LLM 容易迷失在细节中，忘记全局目标。

agent-plus.py 引入了一个可选的规划阶段：

```python
def create_plan(task):
    print("[Planning] Breaking down task...")
    response = client.chat.completions.create(
        model=os.environ.get("OPENAI_MODEL", "gpt-4o-mini"),
        messages=[
            {"role": "system", "content": "Break down the task into 3-5 simple, actionable steps. Return as JSON array of strings."},
            {"role": "user", "content": f"Task: {task}"}
        ],
        response_format={"type": "json_object"}
    )
    try:
        plan_data = json.loads(response.choices[0].message.content)
        steps = plan_data.get("steps", [task])
        print(f"[Plan] {len(steps)} steps created")
        for i, step in enumerate(steps, 1):
            print(f"  {i}. {step}")
        return steps
    except:
        return [task]
```

### 3.2 规划的设计细节

这段代码有几个值得细品的地方：

**用 LLM 来做规划。** 规划本身也是一次 LLM 调用，但不带任何工具——纯粹的"思考"。system prompt 要求 LLM 把任务拆解为 3-5 个可执行的步骤，以 JSON 格式返回。

**结构化输出。** 通过 `response_format={"type": "json_object"}` 强制 LLM 返回 JSON，避免格式解析问题。

**优雅降级。** 如果 JSON 解析失败，`except` 分支回退到 `[task]`——即不拆解，整个任务当作一步执行。这种防御性编程在 Agent 开发中非常重要。

### 3.3 两种执行范式的对比

agent.py 和 agent-plus.py 代表了 Agent 领域的两种经典范式：

```
agent.py (ReAct)                  agent-plus.py (Plan-then-Execute)

思考 → 行动 → 观察                规划（全局思考）
  ↑         │                         │
  └─────────┘                      步骤1 → 步骤2 → 步骤3
                                   (每步内部仍是 ReAct)
```

ReAct 灵活但容易迷失，Plan-then-Execute 有全局视角但规划可能不准确。agent-plus.py 通过 `--plan` 参数让用户自行选择——这种"默认简单，按需复杂"的设计在工程上很实用。

---

## 四、多步执行：步骤之间的上下文传递

### 4.1 从 `run_agent` 到 `run_agent_step` 的关键变化

对比第一篇中 agent.py 的 `run_agent` 函数，agent-plus.py 的 `run_agent_step` 有两个关键变化：

```python
def run_agent_step(task, messages, max_iterations=5):
    messages.append({"role": "user", "content": task})
    actions = []

    for _ in range(max_iterations):
        response = client.chat.completions.create(
            model=os.environ.get("OPENAI_MODEL", "gpt-4o-mini"),
            messages=messages,
            tools=tools
        )
        message = response.choices[0].message
        messages.append(message)

        if not message.tool_calls:
            return message.content, actions, messages

        for tool_call in message.tool_calls:
            function_name = tool_call.function.name
            function_args = json.loads(tool_call.function.arguments)
            print(f"[Tool] {function_name}({function_args})")
            function_response = available_functions[function_name](**function_args)
            actions.append({"tool": function_name, "args": function_args})
            messages.append({"role": "tool", "tool_call_id": tool_call.id, "content": function_response})

    return "Max iterations reached", actions, messages
```

**变化一：`messages` 从内部创建变为外部传入。** 这意味着多个步骤可以共享同一个对话历史。步骤 1 执行 `grep` 搜索到的结果，在步骤 2 中仍然可见。

**变化二：返回值包含 `messages`。** 函数把更新后的消息列表返回给调用方，供下一步继续使用。

### 4.2 编排层：把步骤串起来

```python
all_results = []
for i, step in enumerate(steps, 1):
    if len(steps) > 1:
        print(f"\n[Step {i}/{len(steps)}] {step}")
    result, actions, messages = run_agent_step(step, messages)
    all_results.append(result)

final_result = "\n".join(all_results)
save_memory(task, final_result)
```

**`messages` 变量在整个步骤循环中是同一个列表对象。** 步骤 1 执行过程中产生的所有工具调用和结果，都会累积在这个列表中，步骤 2 的 LLM 调用能看到步骤 1 的完整执行轨迹。

这引出了一个重要的概念区分——**短期记忆与长期记忆**：

| 记忆类型 | 载体 | 生命周期 | 实现 |
|----------|------|----------|------|
| 短期记忆 | `messages` 列表 | 单次运行内 | 步骤间共享的对话历史 |
| 长期记忆 | `agent_memory.md` 文件 | 跨多次运行 | system prompt 中的 "Previous context" |

---

## 五、完整运行时序示例

以 `python agent-plus.py --plan "找到所有 TODO 并整理到 todo.md"` 为例：

```
[Planning] Breaking down task...
[Plan] 3 steps created
  1. 使用 grep 递归搜索所有 TODO 注释
  2. 整理搜索结果为 Markdown 清单格式
  3. 将清单写入 todo.md

[Step 1/3] 使用 grep 递归搜索所有 TODO 注释
[Tool] execute_bash({"command": "grep -rn 'TODO' --include='*.py' ."})
  → ./app.py:23: # TODO: add error handling
  → ./utils.py:7: # TODO: refactor this function
  → ./main.py:45: # TODO: add logging

找到 3 处 TODO 注释。

[Step 2/3] 整理搜索结果为 Markdown 清单格式
（LLM 看到步骤 1 的 grep 结果，直接整理，无需再次搜索）

已整理为以下清单：
- app.py:23 - add error handling
- utils.py:7 - refactor this function
- main.py:45 - add logging

[Step 3/3] 将清单写入 todo.md
[Tool] write_file({"path": "todo.md", "content": "# TODO List\n\n..."})

已将 TODO 清单写入 todo.md。
```

注意步骤 2 没有调用任何工具——LLM 直接从 `messages` 中读取了步骤 1 的 grep 输出并整理。这就是上下文传递的威力。

---

## 六、记忆方案的局限与进化方向

nanoAgent 的记忆方案堪称"最小可行记忆"，但它清晰地暴露了四个需要进化的方向：

**记忆无差别截断** → **向量数据库 + 语义检索**。只保留最后 50 行会丢失重要的早期信息。更好的方案是把记忆存入向量数据库（如 Chroma、Pinecone），每次只检索与当前任务语义相关的记忆。这就是 RAG 的核心思路。

**无记忆压缩** → **记忆蒸馏**。当记忆超过阈值时，用 LLM 自动压缩旧记忆——提取关键事实，丢弃细节。比如把"执行了 grep -rn TODO，找到 app.py:23、utils.py:7、main.py:45 三处"压缩为"项目中有 3 处 TODO 待处理"。

**全量注入 prompt** → **记忆作为工具**。不把记忆塞进 system prompt，而是提供一个 `search_memory` 工具让 Agent 按需查询。Agent 自己决定什么时候需要回忆、回忆什么。

**单层记忆** → **分层记忆架构**。参考人类记忆的工作方式：工作记忆（当前 messages）→ 短期记忆（最近几次对话摘要）→ 长期记忆（压缩后的关键事实）。每层的信息密度和保留时间不同。

---

## 七、总结与下一篇预告

|  | agent.py | agent-plus.py |
|--|----------|---------------|
| 类比 | 金鱼——做完就忘 | 带笔记本的实习生——会记录、会规划 |
| 记忆 | 无 | 文件持久化 + prompt 注入 |
| 规划 | 无（走一步看一步） | 可选的 Plan-then-Execute |
| 执行 | 单任务单循环 | 多步串联，上下文共享 |

三个核心启示：

**1. 记忆的本质是"信息搬运"。** LLM 没有真正的记忆，所有记忆都是把外部存储的信息搬运到 prompt 中。不同方案的区别只在于"存在哪、怎么找、搬多少"。

**2. 规划让 Agent 有了全局视角。** 没有规划的 Agent 像是蒙着眼走迷宫；有规划的 Agent 至少先看了一眼地图。虽然地图可能不准确，但总比没有强。

**3. 上下文传递是多步执行的关键。** `messages` 列表在步骤间的共享，让后续步骤能利用前面步骤的执行结果，避免重复工作。

---

现在我们的 Agent 有了记忆和规划能力，但还有三个问题没解决：

- **工具是硬编码的**——想接入 Slack、GitHub、数据库等外部服务怎么办？
- **没有行为约束**——不同项目、不同团队对 Agent 的要求完全不同，怎么定制？
- **规划是被动触发的**——用户必须手动加 `--plan` 参数，Agent 自己不知道什么时候该规划。

这三个问题，引出了 Agent 架构中最后也是最精彩的三个概念：**MCP（工具协议）**、**Rules（行为规则）**、**Skills（技能注册）**。如果你用过 OpenClaw 或 Claude Code，你一定见过 `CLAUDE.md` 规则文件和 MCP 工具配置——它们正是这三个概念的工程化产物。在 [第三篇：Rules、Skills 与 MCP](./nanoAgent-03-skills-mcp.md) 中，我们将看到 agent-claudecode.py 如何用 265 行代码，把 nanoAgent 进化为一个接近 OpenClaw / Claude Code 的完整 Agent 框架。

---

*本文基于 [sanbuphy/nanoAgent](https://github.com/sanbuphy/nanoAgent) 的 agent-plus.py 分析。如果你还没有读过系列第一篇，建议先从 [底层原理，只有 115 行](./nanoAgent-01-essence.md) 开始。*
