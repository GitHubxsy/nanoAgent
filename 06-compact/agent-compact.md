# 从零开始理解 Agent（六）：Agent 的一次断舍离——上下文压缩

> **「从零开始理解 Agent」系列** —— 从一个极简开源项目 [nanoAgent](https://github.com/GitHubxsy/nanoAgent) 出发，逐层拆解 OpenClaw / Claude Code 等 AI Agent 背后的全部核心概念。
>
> - [第一篇：底层原理，只有 100 行](../01-essence/agent-essence.md) —— 工具 + 循环
> - [第二篇：记忆与规划](../02-memory/agent-memory.md) —— 182 行
> - [第三篇：Rules、Skills 与 MCP](../03-skills-mcp/agent-skills-mcp.md) —— 265 行
> - [第四篇：SubAgent 子智能体](../04-subagent/agent-subagent.md) —— 192 行
> - [第五篇：多智能体协作与编排](../05-teams/agent-teams.md) —— 270 行
> - **第六篇：上下文压缩**（本文）—— 169 行
> - [第七篇：安全与权限控制](../07-safety/agent-safe.md) —— 219 行

前五篇我们不断给 Agent 加能力：工具、记忆、规划、Rules、SubAgent、Teams……但有一个问题我们一直在回避：**Agent 的对话历史会无限增长，直到撑爆 LLM 的 context window。**

这不是"将来可能遇到的问题"，而是"用 Agent 干稍微复杂点的活就一定会遇到的问题"。

今天我们回到 agent-essence.py 的极简基础上，只加一个函数（约 30 行），实现最简单的上下文压缩。

> **关于本篇代码的说明：**
>
> 和第四、五篇一样，本篇的 `agent-compact.py` 是我们**新开发的文件**（[GitHub 源码](https://github.com/GitHubxsy/nanoAgent/blob/main/06-compact/agent-compact.py)），不在 nanoAgent 原始仓库中。它基于第一篇的 `agent-essence.py`，只新增了一个 `compact_messages()` 函数来演示压缩机制。为了让压缩逻辑尽可能清晰，没有加入记忆、规划、Rules 等其他功能。

---

## 一、先搞清楚问题：为什么 messages 会爆？

回忆第一篇中 Agent 的核心循环。每一轮循环，`messages` 列表都会新增至少两条消息：

```
第 1 轮: messages += [LLM的回复, 工具的返回结果]
第 2 轮: messages += [LLM的回复, 工具的返回结果]
第 3 轮: messages += [LLM的回复, 工具的返回结果]
...
```

假设一个任务需要 Agent 调用 15 次工具（对于"找到所有 Python 文件、统计行数、排序、写入报告"这样的任务完全正常），`messages` 就会累积到 30+ 条，其中每条工具返回结果可能包含几百行的命令输出。

而**任何 LLM 的 context window 都是有限的**。不管是几万 tokens 还是几十万 tokens，只要 Agent 读几个大文件（每个几千行）、执行几次 grep 返回大量结果、再来几轮工具调用——窗口就会被迅速填满。尤其是本地部署的小模型，context window 往往只有几千 tokens，几轮循环就会触顶。

> 你可能会想："现在的模型 context window 越来越大了，还需要压缩吗？"
>
> 需要。窗口变大只是推迟了问题，没有消除问题。而且更长的上下文意味着更高的 token 费用、更慢的响应速度、以及 LLM 在超长文本中"迷失重点"的风险（即 lost in the middle 问题）。

当 messages 超过 context window，API 直接报错：`context_length_exceeded`。Agent 挂了，任务半途而废。

---

## 二、能不能不压缩？

在看解决方案之前，先想想有没有其他出路：

**方案 A：用更大 context window 的模型。** 能缓解，但不能根治。窗口再大，Agent 读几个大文件、跑几次搜索也会填满。而且更大的窗口意味着更高的 token 费用、更慢的响应速度、以及 LLM 在超长文本中丢失重点的风险。

**方案 B：限制最大循环次数。** 第一篇中的 `max_iterations=5` 就是这个思路。但这只是把问题从"撑爆"变成了"做不完"——复杂任务就是需要很多轮。

**方案 C：截断工具返回结果。** 比如 `bash` 命令输出超过 1000 字符就截断。能减缓增长速度，但治标不治本，而且截断可能丢失关键信息。

**方案 D：压缩旧的对话历史。** 把早期的详细对话压缩成一段摘要，只保留要点。Agent 继续工作时，靠摘要"回忆"之前做了什么，靠最近几条消息保持当前操作的精确上下文。

方案 D 就是上下文压缩（Context Compaction）。它不需要换模型，不限制能力，不丢失关键信息——**用 LLM 自己来总结自己的历史，然后轻装上阵继续干活。**

---

## 三、压缩的原理：一张图看懂

```
压缩前的 messages（30 条，快爆了）:
┌────────┐
│ system │ ← 永远保留
├────────┤
│ user   │ ← 最初的任务
│ assist │ ← LLM 调用了 bash
│ tool   │ ← bash 输出了 200 行文件列表
│ assist │ ← LLM 调用了 read_file
│ tool   │ ← 文件内容 500 行            ─┐
│ assist │ ← LLM 决定统计行数            │
│ tool   │ ← 统计结果                    │ 这些旧消息
│ assist │ ← LLM 调用了 grep             │ 交给 LLM 做摘要
│ tool   │ ← grep 结果 300 行            │
│ ...    │ ← 更多历史                   ─┘
│ assist │ ← LLM 准备写文件             ─┐
│ tool   │ ← 写入成功                    │ 最近 6 条
│ assist │ ← LLM 调用 read 验证         │ 保留原样
│ tool   │ ← 文件内容                    │ （不压缩）
│ assist │ ← LLM 准备做最后总结         │
│ user   │ ← 当前操作                   ─┘
└────────┘

        ↓ compact_messages() ↓

压缩后的 messages（9 条，清爽了）:
┌────────┐
│ system │ ← 永远保留（不动）
├────────┤
│ user   │ ← "之前的对话摘要：找到了 42 个 Python 文件，
│        │    统计了行数，最长的是 utils.py (350行)..."
│ assist │ ← "明白了，我继续。"
├────────┤
│ assist │ ← LLM 准备写文件             ─┐
│ tool   │ ← 写入成功                    │ 最近 6 条
│ assist │ ← LLM 调用 read 验证         │ 完整保留
│ tool   │ ← 文件内容                    │
│ assist │ ← LLM 准备做最后总结         │
│ user   │ ← 当前操作                   ─┘
└────────┘
```

核心思想就一句话：**记住要点，忘掉细节，保留现场。**

---

## 四、代码实现：只有一个函数

整个压缩逻辑只有一个函数 `compact_messages()`，约 30 行：

```python
COMPACT_THRESHOLD = 20  # 超过 20 条就压缩
KEEP_RECENT = 6         # 保留最近 6 条不压缩

def compact_messages(messages):
    if len(messages) <= COMPACT_THRESHOLD:
        return messages  # 没超阈值，不压缩

    system_msg = messages[0]                   # system prompt 永远保留
    old_messages = messages[1:-KEEP_RECENT]     # 旧消息 → 要被压缩
    recent_messages = messages[-KEEP_RECENT:]   # 最近的消息 → 保留原样

    # 把旧消息拼成文本
    old_text = ""
    for msg in old_messages:
        role = msg.get("role", "unknown") if isinstance(msg, dict) else getattr(msg, "role", "unknown")
        content = msg.get("content", "") if isinstance(msg, dict) else getattr(msg, "content", "")
        if content:
            old_text += f"[{role}]: {content}\n"

    # 调用 LLM 生成摘要
    summary_response = client.chat.completions.create(
        model=MODEL,
        messages=[
            {"role": "system", "content": "Summarize the following conversation history. Keep all important facts, file paths, command results, and decisions. Be concise but don't lose critical details."},
            {"role": "user", "content": old_text}
        ]
    )
    summary = summary_response.choices[0].message.content

    # 重新组装
    return [
        system_msg,
        {"role": "user", "content": f"[Previous conversation summary]: {summary}"},
        {"role": "assistant", "content": "Understood. I have the context from our previous conversation. Let me continue."},
        *recent_messages
    ]
```

### 4.1 分三刀

```python
system_msg = messages[0]                   # 第一刀：切出 system prompt
old_messages = messages[1:-KEEP_RECENT]     # 第二刀：切出旧消息（要压缩的）
recent_messages = messages[-KEEP_RECENT:]   # 第三刀：切出最近消息（要保留的）
```

为什么 system prompt 要单独保留？因为它包含 Agent 的核心指令，压缩进摘要会丢失"你是谁、你能做什么"的基础设定。

为什么最近 N 条不压缩？因为 Agent 当前正在进行的操作需要精确的上下文——比如上一条工具返回的文件内容、正在写入的文件路径。这些信息一旦被压缩成摘要，LLM 就无法精确引用了。

### 4.2 用 LLM 做摘要

```python
summary_response = client.chat.completions.create(
    model=MODEL,
    messages=[
        {"role": "system", "content": "Summarize... Keep all important facts..."},
        {"role": "user", "content": old_text}
    ]
)
```

这里有一个"套娃"——**用 LLM 来压缩 LLM 的对话历史**。这不是浪费吗？不是。因为这次 LLM 调用的唯一任务就是"总结"，不带工具，输出简短，token 开销远小于把完整历史塞进每次请求。

### 4.3 在循环中调用

Agent 核心循环里只加了一行：

```python
def run_agent(user_message, max_iterations=30):
    messages = [...]

    for i in range(max_iterations):
        messages = compact_messages(messages)  # ← 就这一行
        response = client.chat.completions.create(...)
        ...
```

每轮循环开始前检查一次。没超阈值就原样返回（零开销），超了就压缩。简洁到几乎不存在。

---

## 五、压缩过程的实际观察

以下是测试中观察到的 messages 数量变化（阈值设为 10）：

```
轮次 1: messages = 2   (system + user)
轮次 2: messages = 4   (+ assistant + tool)
轮次 3: messages = 6
轮次 4: messages = 8
轮次 5: messages = 10
         ↓ 触发压缩！
轮次 6: messages = 9   (system + 摘要 + ack + 最近6条)
轮次 7: messages = 11
         ↓ 再次触发压缩！
轮次 8: messages = 9
轮次 9: 任务完成
```

messages 数量像锯齿波一样：涨到阈值 → 压缩回去 → 继续涨 → 再压缩。**永远不会超过阈值太多，Agent 可以无限工作下去。**

---

## 六、压缩会丢信息吗？

会。但关键是**丢的是细节，不是要点**。

比如原始历史中有：
```
[tool]: $ find . -name "*.py" | head -20
./src/utils.py
./src/main.py
./src/config.py
./tests/test_utils.py
./tests/test_main.py
（省略 15 个文件）
```

压缩后摘要可能变成：
```
在当前目录下找到了 20 个 Python 文件，分布在 src/ 和 tests/ 两个目录中。
```

20 个具体文件名丢了，但"有 20 个文件、在 src/ 和 tests/ 下"这个关键事实保留了。对于 Agent 后续的决策（比如"接下来统计行数"），这个摘要已经足够。

如果某个细节真的还需要呢？Agent 可以再次调用工具去获取。这就像人类的工作方式——"我记得上周查过这个目录有 20 个 Python 文件，但具体哪些我忘了，让我再 `ls` 一下。"

---

## 七、压缩方案的对比：nanoAgent vs 业界

nanoAgent 的压缩是最朴素的实现。业界的方案更加精细：

| 维度 | agent-compact.py | OpenClaw / Claude Code 等生产级实现 |
|------|-----------------|-------------------------------------|
| 触发条件 | 消息条数超过固定阈值 | 基于 token 数精确计算，考虑模型的实际窗口大小 |
| 压缩方式 | 一次性把所有旧消息压缩成一段摘要 | 分层压缩：最近的保留原文，稍远的做摘要，更远的只保留关键事实 |
| 保留策略 | 固定保留最近 N 条 | 智能选择：保留包含文件路径、错误信息等关键消息 |
| 摘要质量 | 通用摘要 prompt | 针对 coding 场景优化的摘要 prompt，确保保留文件路径、代码片段、决策原因 |

但核心思路完全一致：**旧的压缩，近的保留，要点不丢。**

---

## 八、系列回顾：六篇文章的完整拼图

| 篇 | 核心主题 | 解决什么问题 |
|----|---------|------------|
| 一 | 工具 + 循环 | Agent 如何自主工作 |
| 二 | 记忆 + 规划 | Agent 如何记住过去、规划未来 |
| 三 | Rules + Skills + MCP | Agent 如何扩展知识和工具 |
| 四 | SubAgent | Agent 如何临时找帮手 |
| 五 | Teams | Agent 如何组建持久团队 |
| **六** | **上下文压缩** | **Agent 如何在有限窗口内持续工作** |

前五篇是在给 Agent "加能力"，第六篇是在解决加完能力后的"副作用"。能力越强、工具越多、协作越复杂，对话历史就越长——而压缩确保了这一切不会让 Agent 自我窒息。

如果把 Agent 比作一个人：

- 第一篇给了他**手脚**（工具）
- 第二篇给了他**笔记本**（记忆）和**地图**（规划）
- 第三篇给了他**规章制度**和**工具箱**
- 第四篇让他**能叫临时工帮忙**
- 第五篇让他**组建正式团队**
- 第六篇教他**学会"抓大放小"**——记住要点、忘掉细节、轻装上阵

但前六篇一直在回答"Agent 能做什么"，有一个同样重要的问题我们还没回答："Agent 不能做什么？" 当 Agent 试图执行 `rm -rf /` 时，谁来踩刹车？

这就是 [第七篇：安全与权限控制](../07-safety/agent-safe.md) 的主题：三道安全防线，让 Agent 从"裸奔"变成"有保险的"。

---

*本文基于 agent-compact.py（[GitHub 源码](https://github.com/GitHubxsy/nanoAgent/blob/main/06-compact/agent-compact.py)）分析。完整系列：[第一篇](../01-essence/agent-essence.md) → [第二篇](../02-memory/agent-memory.md) → [第三篇](../03-skills-mcp/agent-skills-mcp.md) → [第四篇](../04-subagent/agent-subagent.md) → [第五篇](../05-teams/agent-teams.md) → 第六篇（本文） → [第七篇](../07-safety/agent-safe.md)*
