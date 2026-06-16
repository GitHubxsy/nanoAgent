# 从零开始理解 Agent（番外篇）：Chat 和 Agent 到底有什么不同？——同一个 LLM，两种根本不同的范式

> **「从零开始理解 Agent」系列** —— 通过一个不到 300 行的开源项目 [nanoAgent](https://github.com/GitHubxsy/nanoAgent)，逐层拆解 AI Agent 背后的主要机制。
>
> 这是系列的一篇番外。[第一篇](./agent-essence.md)讲的是 Agent 的代码实现——工具、循环、逐行拆解。这篇换一个角度：不写代码，而是回答一个更本质的问题——**Agent 和普通 Chat 到底有什么不同？**
>
> 它们用的是同一个 LLM、同一个 API，为什么体验完全不一样？

很多人用过 ChatGPT 的对话模式，也用过 Claude Code 这样的 Agent 模式。直觉上知道它们不一样——一个是"你问我答"，一个是"你说目标，我来搞定"。但"不一样"具体体现在哪里？为什么加了一个循环，一切就变了？

这篇番外从五个维度拆开这个差异：调用方式、控制流、记忆模型、工具依赖、错误恢复。最后给出一张完整对比表和实用的选型建议。

---

## 引子：同一个任务，两种体验

先看一个具体例子。任务：**找到当前项目所有 Python 文件，统计总行数，把报告写入 `report.txt`。**

### 用 Chat 做

```text
你: 找到所有 Python 文件，统计总行数，写入 report.txt
  │
  ▼
LLM: 你可以运行以下命令：
      find . -name "*.py" | xargs wc -l | tail -1
      然后用 echo 把结果写入 report.txt
  │
  ▼
你: （手动执行 find 命令）→ 得到 "12345 total"
你: （手动执行 echo 命令）→ 写入 report.txt
你: 做完了
```

三次交互。你问了，它答了，**你自己执行**。每一步做什么，你来决定。

### 用 Agent 做

```text
你: 找到所有 Python 文件，统计总行数，写入 report.txt
  │
  ▼
Agent: [Tool] execute_bash("find . -name '*.py' | xargs wc -l | tail -1")
       → "12345 total"
       [Tool] write_file("report.txt", "Total Python lines: 12345")
       → "Wrote to report.txt"
       "已完成。共 12345 行 Python 代码，结果已写入 report.txt。"
```

一次交互。你给了目标，**它自己执行**。每一步做什么，LLM 决定。

同一个 LLM，同一个 API。一个像顾问——你问它答；一个像助理——你下指令它干活。差异不在模型，在**谁握着方向盘**。

---

## 一、同一个 API，两种调用方式

Chat 和 Agent 调用的是完全相同的 API：

```python
client.chat.completions.create(model=MODEL, messages=messages, ...)
```

区别在于**怎么调**。

### Chat：一次调用

```python
response = client.chat.completions.create(model=MODEL, messages=messages)
print(response.choices[0].message.content)  # 拿到回答，结束
```

```text
request  →  response  →  结束
```

用户发消息，LLM 返回文本，完事。一次请求，一次响应，一条直线。

### Agent：循环调用

```python
for _ in range(max_iterations):
    response = client.chat.completions.create(
        model=MODEL, messages=messages, tools=tools
    )
    if not response.choices[0].message.tool_calls:
        break  # LLM 说"我做完了"
    # 执行工具，结果追加到 messages，继续循环
```

```text
request → response → 执行工具 → request → response → 执行工具 → ... → 结束
```

同一个函数，反复调用。每轮之间，代码执行 LLM 请求的工具，把结果塞回 `messages`，再让 LLM 看着结果继续决策。

**关键洞察：循环不在 LLM 里，在你的 Python 代码里。** LLM 从头到尾不知道自己"在循环中"——对它来说，每次 API 调用都是独立的，只不过 `messages` 列表越来越长。它只看到一段更长的上下文，里面多了一些"工具调用 + 工具结果"的记录。

> 详见 [agent-essence.py](./agent-essence.py) 第 124 行的 `for` 循环。

---

## 二、谁决定"下一步做什么"——控制流的反转

这是 Chat 和 Agent **最深层的范式差异**。

### Chat：人驱动

```text
人提问 → LLM 回答 → 人思考 → 人提问 → LLM 回答 → 人思考 → ...
```

人是编排者。LLM 是顾问——你问，它答，你决定下一步问什么。控制权始终在人手里。

### Agent：LLM 驱动

```text
人给目标 → LLM 决定第 1 步 → 代码执行 → LLM 决定第 2 步 → 代码执行 → ... → LLM 说完成了
```

LLM 是编排者。人是委托者——你给一个目标，等待，拿到结果。控制权转移给了 LLM。

这就是**控制流反转**（Control-Flow Inversion）：决策的主体从人变成了 LLM。在 `agent-essence.py` 里，这个反转发生在一行代码：

```python
if not message.tool_calls:  # 第 135 行
    return message.content   # LLM 自己决定"做完了"
```

LLM 自己判断是继续（调用工具）还是停止（返回文本）。人不参与中间决策。

| 决策 | Chat 谁决定 | Agent 谁决定 |
|------|------------|-------------|
| 用什么工具 | 人（人自己执行） | LLM |
| 下一步做什么 | 人 | LLM |
| 何时停止 | 人（不问了就停） | LLM（不调工具就停） |
| 出错了怎么办 | 人（换种方式问） | LLM（看到错误后自己换策略） |

一句话：**Chat 是人驱动的对话，Agent 是 LLM 驱动的自主执行。同一个 API，控制权从人转移到了 LLM。**

---

## 三、记忆模型的根本差异——平面对话 vs 行动轨迹

Chat 和 Agent 都用 `messages` 列表做记忆。但这个列表的**形状**完全不同。

### Chat 的 messages：平面对话

```text
[system, user, assistant, user, assistant, user, assistant]
```

交替出现。每条都是自然语言。结构对称、可预测。像一份聊天记录。

### Agent 的 messages：行动轨迹

```text
[system, user, assistant(tool_call), tool(result), assistant(tool_call), tool(result), assistant(text)]
```

不对衬。夹杂着工具调用（结构化 JSON）和工具结果（命令输出、文件内容、错误信息）。像一份实验记录——"我做了什么、看到了什么、接下来决定做什么"。

### 形状差异的后果

**增长速度不同。** Chat 每轮 +2 条消息（一问一答）。Agent 每次工具调用就 +2 条，而且一次 LLM 回复可以调用多个工具。一个 5 步的 Agent 任务可能产生 12-15 条消息。

**内容类型不同。** Chat 里全是自然语言。Agent 里混着自然语言、JSON、命令输出、文件内容、错误堆栈。这让 Agent 的上下文更"吵"——LLM 需要从大段日志中提取关键信息。

**压缩难度不同。** Chat 历史可以概括为"我们讨论了 X、Y、Z"。Agent 历史不能简单概括——你需要知道*读了哪些文件*、*执行了什么命令*、*遇到了什么错误*。这正是 Agent 系列需要[第六篇：上下文压缩](../06-compact/agent-compact.md)的原因——压缩是 Agent 独有的问题。

一句话：**Chat 的记忆是一条平坦的对话记录，Agent 的记忆是一条带有工具调用和执行结果的工作轨迹。记忆形状不同，很多下游问题（压缩、成本、错误恢复）只在 Agent 中出现。**

---

## 四、没有工具，就没有 Agent

循环不是 Agent 的全部。想一个思想实验：把 `agent-essence.py` 第 130 行的 `tools=tools` 删掉，会发生什么？

```python
# 原来的调用（有工具）
response = client.chat.completions.create(model=MODEL, messages=messages, tools=tools)

# 去掉 tools 后
response = client.chat.completions.create(model=MODEL, messages=messages)
```

1. LLM 收到用户消息，没有工具说明书。
2. 它只能生成文本回答。
3. `not message.tool_calls` 在第一轮就是 `True`。
4. 循环立即退出。**Agent 退化为 Chat。**

这就是公式 **Agent = LLM + 工具 + 循环** 的含义——三个要素不是独立的，而是相互依存的：

```text
LLM + 循环，没工具 → 一个和自己对话的聊天机器人（空转）
LLM + 工具，没循环 → 一次性工具调用器（只能做一步）
工具 + 循环，没 LLM → 一段普通脚本（没有智能）
```

三者缺一不可。工具让 LLM 从"只能说"变成"能做"，循环让 LLM 从"做一步"变成"做完一整件事"。

---

## 五、错误恢复——人纠错 vs 自纠错

任务执行中一定会出错。两种范式处理错误的方式截然不同。

### Chat：人发现、人纠正

```text
你: 列出 src 目录下所有 Python 文件
LLM: 你可以运行 find . -name "*.py"
你: （运行命令，发现结果里混了其他目录的文件）
你: 不对，我要的是 src 目录下的
LLM: 那你运行 find src -name "*.py"
```

人检测到错误（看输出发现不对），人决定纠正方向，人告诉 LLM 重新来。

### Agent：自发现、自纠正

```text
你: 列出 src 目录下所有 Python 文件
Agent: [Tool] execute_bash("find . -name '*.py'")          ← 路径不对
       → 结果里混了非 src 目录的文件
       Agent 看到 tool result，发现结果不对
Agent: [Tool] execute_bash("find src -name '*.py'")        ← 自己修正
       → 正确结果
```

LLM 通过阅读工具返回结果**自己发现**错误，**自己决定**纠正策略，**自己执行**修正。

关键机制在于：**工具返回的结果是反馈信号。** 在 `agent-essence.py` 第 151 行，工具结果被追加到 `messages`：

```python
messages.append({"role": "tool", "tool_call_id": tool_call.id, "content": result})
```

没有这一行，LLM 就看不到自己做了什么，也无法自纠错。

这也是为什么工具函数里的 `try-except`（第 83-86 行）很重要——错误必须作为文本返回给 LLM，而不是让程序崩溃。LLM 需要**看到错误**才能从错误中恢复：

```python
def execute_bash(command):
    result = subprocess.run(command, shell=True, capture_output=True, text=True)
    return result.stdout + result.stderr  # stdout + stderr 都返回，错误信息不丢弃
```

一句话：**Chat 靠人纠错，Agent 靠工具返回结果的反馈自纠错。错误信息不是终点，而是下一轮决策的输入。**

---

## 六、一张图看清全貌

前五节从不同维度分析了 Chat 和 Agent 的差异。这张表把它们合在一起，并加了一列"为什么不同"——每个维度差异的根源。

| 维度 | Chat | Agent | 为什么不同 |
|------|------|-------|-----------|
| 调用模式 | 单次 API 调用 | 循环调用同一 API | 控制流反转 |
| 控制权 | 人驱动 | LLM 驱动 | 谁决定下一步 |
| 记忆形状 | 平面对话记录 | 行动-观察轨迹 | 有无工具结果 |
| 能力边界 | 只能生成文本 | 可以操作真实世界 | 有无工具 |
| 错误恢复 | 人发现、人纠正 | LLM 自发现、自纠正 | 反馈信号来源 |
| 停止条件 | 人不问了 | LLM 不调工具了 | 谁判断"做完了" |
| Token 消耗 | 可预测 | 不可预测（依赖循环次数） | 循环的代价 |
| 适用场景 | 问答、写作、翻译 | 多步骤任务、自动化 | 任务复杂度 |

8 个维度的差异，根源只有两个：**有没有工具，谁掌握控制权。**

---

## 七、什么时候用 Chat，什么时候用 Agent

分析完了差异，一个实际的问题：什么时候该用哪个？

### 用 Chat 的场景

- **单步问答**：问一个事实、解释一个概念、翻译一段话
- **纯文本输出**：写文章、改措辞、总结内容
- **需要人在回路**：每一步都需要人工判断和确认
- **成本敏感**：需要精确预测 token 消耗和延迟

### 用 Agent 的场景

- **多步任务**：需要读取文件、执行命令、写入结果等一系列操作
- **需要真实行动**：操作文件系统、调用 API、部署服务
- **流程可自动化**：步骤之间的逻辑 LLM 可以自主推导
- **"发射后不管"**：给定目标，期望自动完成，不需要逐步确认

### 不要忽略中间地带

现实产品往往不是纯粹的 Chat 或 Agent，而是**混合体**：

```text
纯 Chat ◀────────────────────────────────▶ 纯 Agent

ChatGPT    ChatGPT+搜索    Cursor Tab    Claude Code    Devin
(纯对话)   (Chat+1个工具)   (辅助写代码)   (Agent+确认)   (全自动)
```

ChatGPT 加了网页搜索，本质是 Chat + 一个工具。Cursor 的 Tab 补全是纯 Chat，Agent 模式是 Agent。Claude Code 执行操作但会请求确认——Agent 带了一道人工审核。Devin 追求全自动。

**这是一个自主性的光谱，不是非此即彼的二选一。**

一句话：**能一步回答的用 Chat，需要多步执行的用 Agent。不要为了"酷"而把简单问题复杂化。**

---

## 八、回到本质

回到 [agent-essence.py](./agent-essence.py) 那个 100 行的文件。现在再看它，每一行都有了更深的含义：

- 第 124 行的 `for` 循环，就是**控制流反转**——决策权从人交给了 LLM
- 第 130 行的 `tools=tools`，就是**能力边界**的突破——没有它，循环只是空转
- `messages` 从 `[system, user]` 增长到 `[system, user, assistant, tool, assistant, tool, assistant]`，就是**行动轨迹**——不是平面聊天，而是一条带有观察和决策的工作记录
- 工具函数返回 `stdout + stderr`，就是**反馈信号**——错误信息不是垃圾，是自纠错的输入
- 第 135 行的 `if not message.tool_calls`，就是**停止条件**——LLM 自己判断任务是否完成

Chat 和 Agent 用的是完全相同的 LLM。差异不在于模型本身，而在于**你在模型外面写了什么代码**。一个循环改变了一切——但前提是你也给这个循环配备了工具去行动、反馈去学习。

**Agent 不是一种新的 AI。它是用代码把 LLM 的"说"变成了"做"。**

---

### 延伸阅读

- 想看 Agent 的代码实现？读 [第一篇：底层原理](./agent-essence.md)——逐行拆解 agent-essence.py
- 想理解 LLM 为什么能输出工具调用 JSON？读 [从大模型到 Agent](../../llm/10-agent/llm-10-agent.md)——从 token 预测到 Function Calling
- 想知道 Agent 的记忆太长怎么办？读 [第六篇：上下文压缩](../06-compact/agent-compact.md)——自动摘要与上下文管理

---

*本文是「从零开始理解 Agent」系列的番外篇，可与[第一篇：底层原理](./agent-essence.md)对照阅读。完整系列见 [nanoAgent](https://github.com/GitHubxsy/nanoAgent)。*
