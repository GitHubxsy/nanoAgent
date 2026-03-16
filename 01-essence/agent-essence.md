# 从零开始理解 Agent（一）：OpenClaw / Claude Code 的底层原理，只有 115 行

> **「从零开始理解 Agent」系列** —— 通过一个不到 300 行的开源项目 [nanoAgent](https://github.com/sanbuphy/nanoAgent)，逐层拆解 OpenClaw / Claude Code 等 AI Agent 背后的全部核心概念。
>
> - **第一篇：底层原理，只有 115 行**（本文）—— 工具 + 循环
> - [第二篇：记忆与规划](../02-memory/agent-memory.md) —— 206 行
> - [第三篇：Rules、Skills 与 MCP](../03-skills-mcp/agent-skills-mcp.md) —— 282 行
> - [第四篇：SubAgent 子智能体](../04-subagent/agent-subagent.md) —— 192 行
> - [第五篇：多智能体协作与编排](../05-teams/agent-teams.md) —— 270 行
> - [第六篇：上下文压缩](../06-compact/agent-compact.md) —— 169 行
> - [第七篇：安全与权限控制](../07-safety/agent-safe.md) —— 219 行

很多人用过 ChatGPT、Claude 这样的对话式 AI，也听说过 AI Agent 这个概念。最近 OpenClaw、Claude Code 这类 Coding Agent 火遍了整个开发者圈子——它们能自主读代码、改代码、跑测试，完成以前需要人类手动操作的整个开发流程。

但 Agent 到底和普通对话有什么区别？OpenClaw / Claude Code 这类工具的底层原理是什么？Agent 是怎么"使用工具"的？

本文通过逐行解读一个仅 115 行的极简 Agent 实现—— [sanbuphy/nanoAgent](https://github.com/sanbuphy/nanoAgent)，带你彻底搞懂这些问题。理解了这 115 行代码，你就理解了 OpenClaw、Claude Code、Cursor Agent 等一切 Coding Agent 的共同底座。

---

## 一、先说结论：Agent 和普通对话的核心区别

在深入代码之前，先建立一个直觉：

| 维度 | 普通对话（Chat） | Agent |
|------|------------------|-------|
| 交互模式 | 一问一答，用户驱动 | 自主循环，目标驱动 |
| 能力边界 | 只能生成文本 | 可以调用工具，作用于真实世界 |
| 执行流程 | `用户提问 → 模型回答` | `用户下达任务 → 思考 → 调用工具 → 观察 → 继续思考 → ... → 返回答案` |
| 状态管理 | 每轮独立（或简单上下文拼接） | 维护完整的消息历史，包含工具调用与返回结果 |
| 自主性 | 无 | 模型自主决定"下一步做什么"、"用哪个工具"、"何时停止" |

一句话总结：**Agent = LLM + 工具 + 循环**。普通对话是"你问我答"，Agent 是"你给我一个目标，我自己想办法完成"。

这三个要素缺一不可。没有 LLM，就没有"思考"能力；没有工具，就无法作用于真实世界；没有循环，就做不了多步任务。接下来我们看 nanoAgent 是怎么用 115 行代码实现这三要素的。

---

## 二、nanoAgent 全局架构

nanoAgent 的 `agent-essence.py` 只有 115 行，但五脏俱全。整体结构可以拆成四个部分：

```
┌─────────────────────────────────────────┐
│           1. LLM 客户端初始化             │
├─────────────────────────────────────────┤
│           2. 工具定义（Tool Schema）       │
├─────────────────────────────────────────┤
│           3. 工具实现（Tool Functions）    │
├─────────────────────────────────────────┤
│           4. Agent 循环（Core Loop）       │
└─────────────────────────────────────────┘
```

下面逐层拆解。

---

## 三、逐层解读源码

### 3.1 LLM 客户端初始化

```python
import os
import json
import subprocess
import sys
from openai import OpenAI

client = OpenAI(
    api_key=os.environ.get("OPENAI_API_KEY"),
    base_url=os.environ.get("OPENAI_BASE_URL")
)
```

这里用的是 OpenAI 的 Python SDK，但通过 `base_url` 环境变量，可以指向任何兼容 OpenAI API 格式的服务（比如 DeepSeek、Qwen、本地 Ollama 等）。这是一个非常实用的设计——**Agent 框架不绑定具体模型**。

### 3.2 工具定义：告诉 LLM "你有哪些能力"

```python
tools = [
    {
        "type": "function",
        "function": {
            "name": "execute_bash",
            "description": "Execute a bash command on the system",
            "parameters": {
                "type": "object",
                "properties": {
                    "command": {"type": "string", "description": "The bash command to execute"}
                },
                "required": ["command"]
            }
        }
    },
    # ... read_file, write_file 类似
]
```

这是 OpenAI Function Calling 的标准格式。这段 JSON Schema 本质上是一份**工具说明书**，它会随着每次 API 请求一起发送给 LLM。LLM 读到这份说明书后，就"知道"自己可以执行 bash 命令、读文件、写文件。

nanoAgent 定义了三个工具：

| 工具名 | 能力 | 危险等级 |
|--------|------|----------|
| `execute_bash` | 执行任意 shell 命令 | ⚠️ 极高——理论上可以做任何事 |
| `read_file` | 读取文件内容 | 中——可能读到敏感信息 |
| `write_file` | 写入文件 | 高——可以覆盖任何文件 |

> **关键洞察**：LLM 本身不会执行任何代码。它只是根据工具说明书，输出一段结构化的 JSON，表达"我想调用 execute_bash，参数是 ls -la"。**真正的执行发生在我们的 Python 代码里**。这个"LLM 输出意图、代码执行动作"的分工，是理解所有 Agent 系统的关键。

### 3.3 工具实现：把 LLM 的"意图"变成"行动"

```python
def execute_bash(command):
    try:
        result = subprocess.run(command, shell=True, capture_output=True, text=True, timeout=30)
        return result.stdout + result.stderr
    except Exception as e:
        return f"Error: {str(e)}"

def read_file(path):
    try:
        with open(path, 'r') as f:
            return f.read()
    except Exception as e:
        return f"Error: {str(e)}"

def write_file(path, content):
    try:
        with open(path, 'w') as f:
            f.write(content)
        return f"Successfully wrote to {path}"
    except Exception as e:
        return f"Error: {str(e)}"
```

这三个函数就是工具的"真身"。几个值得注意的细节：

**错误处理**：每个函数都用 try-except 包裹，确保即使执行出错也能把错误信息返回给 LLM，而不是让整个程序崩溃。这很重要——LLM 看到错误后可以自行修正策略。

**timeout=30**：bash 命令有 30 秒超时限制，防止死循环或长时间阻塞。

**shell=True**：意味着可以执行管道、重定向等复杂 shell 语法，能力很强，但安全风险也很大。

接下来是一个路由表，把工具名映射到实际函数：

```python
available_functions = {
    "execute_bash": execute_bash,
    "read_file": read_file,
    "write_file": write_file
}
```

这个字典是**工具调度的核心**——当 LLM 说"我要调用 execute_bash"时，代码通过这个字典找到对应的 Python 函数并执行。

### 3.4 Agent 核心循环：最精华的 20 行代码

```python
def run_agent(user_message, max_iterations=5):
    messages = [
        {"role": "system", "content": "You are a helpful assistant that can interact with the system. Be concise."},
        {"role": "user", "content": user_message}
    ]

    for _ in range(max_iterations):
        # Step 1: 把完整对话历史 + 工具列表发给 LLM
        response = client.chat.completions.create(
            model=os.environ.get("OPENAI_MODEL", "gpt-4o-mini"),
            messages=messages,
            tools=tools
        )

        message = response.choices[0].message
        messages.append(message)

        # Step 2: 如果 LLM 没有调用工具 → 任务完成，返回文本回答
        if not message.tool_calls:
            return message.content

        # Step 3: 如果 LLM 要调用工具 → 逐个执行，把结果追加到对话历史
        for tool_call in message.tool_calls:
            function_name = tool_call.function.name
            function_args = json.loads(tool_call.function.arguments)
            print(f"[Tool] {function_name}({function_args})")
            function_response = available_functions[function_name](**function_args)
            messages.append({
                "role": "tool",
                "tool_call_id": tool_call.id,
                "content": function_response
            })

    return "Max iterations reached"
```

这 20 多行代码是整个 Agent 的灵魂。让我逐步拆解这个循环里发生了什么。

---

## 四、Agent 循环的运行时序（核心重点）

以一个具体例子来说明。假设用户运行：

```bash
python 01-essence/agent-essence.py "统计当前目录下有多少个 Python 文件，并把结果写入 count.txt"
```

Agent 的执行过程如下：

### 第 1 轮循环

**发送给 LLM 的 messages：**
```
[system] You are a helpful assistant...
[user]   统计当前目录下有多少个 Python 文件，并把结果写入 count.txt
```

**LLM 返回：** 不是普通文本，而是一个 tool_call：
```json
{
  "tool_calls": [{
    "function": {"name": "execute_bash", "arguments": "{\"command\": \"find . -name '*.py' | wc -l\"}"}
  }]
}
```

**代码执行：** 调用 `execute_bash("find . -name '*.py' | wc -l")`，得到结果 `"42\n"`

**追加到 messages：**
```
[tool] 42
```

### 第 2 轮循环

**发送给 LLM 的 messages：** 现在包含了完整历史（system + user + assistant的tool_call + tool结果）

**LLM 看到**结果是 42，决定写入文件：
```json
{
  "tool_calls": [{
    "function": {"name": "write_file", "arguments": "{\"path\": \"count.txt\", \"content\": \"Python files: 42\"}"}
  }]
}
```

**代码执行：** 调用 `write_file("count.txt", "Python files: 42")`

### 第 3 轮循环

**LLM 看到**文件写入成功，判断任务已完成，返回纯文本：

```
"已统计完成，当前目录下共有 42 个 Python 文件，结果已写入 count.txt。"
```

**`not message.tool_calls` 为 True** → 退出循环，返回结果。

用一张图来表示：

```
用户任务
  │
  ▼
┌──────────────────────────────────────────────────┐
│                  Agent Loop                       │
│                                                   │
│  ┌─────────┐    ┌──────────┐    ┌──────────────┐ │
│  │ 发送给   │───▶│ LLM 决策  │───▶│ 有tool_call? │ │
│  │ LLM     │    │          │    └──────┬───────┘ │
│  └─────────┘    └──────────┘           │         │
│       ▲                          Yes   │   No    │
│       │                          ┌─────┴─────┐   │
│       │                          ▼           ▼   │
│  ┌────┴────────┐          ┌──────────┐  返回文本  │
│  │ 结果追加到   │◀─────────│ 执行工具  │  ──────▶  │
│  │ messages    │          └──────────┘   结束    │
│  └─────────────┘                                 │
└──────────────────────────────────────────────────┘
```

---

## 五、深入理解几个关键设计

### 5.1 为什么需要 `max_iterations`？

```python
for _ in range(max_iterations):  # 默认 5 次
```

这是一个**安全阀**。如果 LLM 陷入死循环（比如反复执行同一个失败的命令），`max_iterations` 确保程序最终会停下来。在生产级 Agent 中，这个值通常更大（比如 Claude Code 可以连续执行数十步），同时会配合更复杂的终止策略。

### 5.2 `messages` 列表为什么如此重要？

`messages` 是 Agent 的**短期记忆**。每一轮循环，它都会累积 LLM 的回复（包括它想调用什么工具）以及工具的执行结果。

当这个列表在下一轮发送给 LLM 时，LLM 能看到完整的"行动-观察"历史，从而做出更合理的下一步决策。这就是 Agent 和简单对话的本质区别——**Agent 维护了一条包含行动轨迹的上下文链**。

但请注意，这里的 `messages` 只在单次运行中存在。程序退出后，一切归零。Agent 下次运行时完全不记得上次做过什么。**这个"失忆"问题，正是我们在[第二篇](../02-memory/agent-memory.md)要解决的。**

### 5.3 LLM 是怎么"决定"调用工具的？

这是最容易产生误解的地方。LLM 并没有真的在"执行代码"或"调用函数"。实际发生的是：

1. 我们在 API 请求中传入了 `tools` 参数（工具说明书）
2. LLM 经过训练，学会了在适当的时候输出一种特殊的结构化格式（tool_calls）
3. 这个格式本质上就是一段 JSON，描述"我想调用哪个函数、传什么参数"
4. **我们的代码**解析这段 JSON，执行真正的函数，再把结果喂回给 LLM

所以整个过程可以理解为一种**协作协议**：

```
LLM 的职责：思考、决策、生成工具调用指令
代码的职责：解析指令、执行工具、返回结果
```

LLM 是"大脑"，代码是"手脚"。

### 5.4 `tool_call_id` 的作用

```python
messages.append({
    "role": "tool",
    "tool_call_id": tool_call.id,
    "content": function_response
})
```

`tool_call_id` 是 OpenAI API 的要求，用于将工具返回结果与对应的调用请求关联起来。当 LLM 在一次回复中同时调用多个工具时（并行调用），这个 ID 确保每个结果能正确匹配到对应的调用。

---

## 六、这个 Agent 还缺什么？

nanoAgent 的极简设计让核心概念一目了然，但如果你仔细想想，会发现它有几个根本性的缺陷：

**1. 没有记忆。** 每次运行都是一张白纸。昨天让它创建的文件，今天问它"你昨天干了什么"，它一脸茫然。

**2. 没有规划。** 面对"重构整个项目"这样的复杂任务，它只能走一步看一步，容易迷失在细节中。

**3. 工具是硬编码的。** 只有 3 个工具，想加新工具必须改代码。没有任何扩展机制。

**4. 没有行为约束。** 它可以执行 `rm -rf /`，没有任何规则告诉它什么该做、什么不该做。

这些缺陷，恰好对应了 Agent 架构中更高层次的需求。nanoAgent 的作者也意识到了这一点，所以他写了两个进化版本来逐一解决。

---

## 七、从 nanoAgent 看 Agent 的本质

回到最初的问题：Agent 到底是什么？

通过 nanoAgent 的 115 行代码，我们可以提炼出 Agent 的三个本质要素：

**1. 感知（Perception）**—— 通过工具获取外部信息（read_file、execute_bash 的输出）

**2. 决策（Reasoning）**—— LLM 根据任务目标和已有观察，决定下一步行动

**3. 行动（Action）**—— 通过工具作用于外部环境（write_file、execute_bash）

这三者在一个循环中不断迭代，直到 LLM 判断任务完成（不再调用工具）。这就是 Agent 最朴素、最本质的运行方式——**"思考 → 行动 → 观察"（ReAct）**范式。

无论是 OpenClaw、Claude Code、Cursor 还是 Devin，底层都遵循这个范式。当你在 OpenClaw 中看到它自动 `grep` 搜索代码、`edit` 修改文件、`bash` 跑测试时，背后就是这样一个循环在驱动。nanoAgent 用最少的代码，把这个范式展现得淋漓尽致。

---

## 八、动手试一试

如果你想亲手体验，只需：

```bash
# 克隆项目
git clone https://github.com/sanbuphy/nanoAgent.git
cd nanoAgent

# 设置环境变量（可以用任何兼容 OpenAI API 的服务）
export OPENAI_API_KEY="your-key"
export OPENAI_BASE_URL="https://api.openai.com/v1"  # 或 DeepSeek/Qwen 等

# 运行
python 01-essence/agent-essence.py "帮我创建一个 hello.py 文件，内容是打印当前时间"
```

然后观察终端输出的 `[Tool]` 日志，你就能清晰地看到 Agent 的每一步决策和行动。

---

## 下一篇预告

现在我们有了一个能干活的 Agent，但它像一条金鱼——做完就忘。如何让 Agent 拥有记忆，记住之前做过的事？如何让它面对复杂任务时先规划再执行，而不是蒙头乱撞？

这些问题，我们在 [第二篇：记忆与规划](../02-memory/agent-memory.md) 中解答。代码只多了 67 行，但能力产生质变。

---

*本文基于 [sanbuphy/nanoAgent](https://github.com/sanbuphy/nanoAgent) 项目分析，感谢作者用极简的代码诠释了 Agent 的核心思想。*
