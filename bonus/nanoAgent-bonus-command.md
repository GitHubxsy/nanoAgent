# 从零开始理解 Agent（番外篇）：Command——不是所有操作都要过大脑

> 系列文章从第一篇起，我们建立了一个核心心智模型：`用户输入 → LLM 思考 → 调用工具 → 观察结果 → 继续思考 → ... → 返回答案`。这个循环是 Agent 的大脑。但现实中，有些操作根本不需要经过大脑。

---

## 一、一个尴尬的场景

假设你对 Agent 说：

```
/help
```

会发生什么？

Agent 把 `/help` 当作普通用户输入，塞进 messages，发给 LLM。LLM 认认真真地"思考"了一下，生成了一段帮助文本返回给你。

能用吗？能用。但问题是：

- **浪费了一次 API 调用**。帮助信息是固定的，根本不需要 LLM 生成。
- **浪费了 token**。这条消息还会留在 messages 里，占用后续对话的上下文窗口。
- **结果不稳定**。LLM 每次生成的帮助文本可能不一样，格式也不统一。

再试一个：

```
/clear
```

你只是想清空对话历史，重新开始。但 LLM 不知道你在说什么——它没有"清空 messages 列表"这个工具，只能回复一句"好的，我们重新开始吧"，然后 messages 列表一条都没少。

**这两个例子暴露了一个事实：Agent 的主循环是为"需要思考的任务"设计的，而有些操作天然不需要思考。** 让 LLM 处理这些操作，就像让一个高级工程师帮你开关灯——能做，但没必要。

---

## 二、Command：主循环的旁路

解决方案很简单：在用户输入进入 `run_agent` 之前，先过一道"分流器"。如果输入匹配某个已知命令，直接在本地执行；否则再走正常的 LLM 循环。

```
用户输入
  │
  ▼
以 / 开头？──是──▶ Command Router ──▶ 直接执行，返回结果
  │
  否
  │
  ▼
run_agent()（第一篇的核心循环）
```

用第一篇的 `run_agent` 来说，改动只有一个地方——在调用 `run_agent` 之前加一层判断：

```python
def main():
    messages = [{"role": "system", "content": SYSTEM_PROMPT}]

    while True:
        user_input = input("\nYou: ").strip()
        if not user_input:
            continue

        # ---- 新增：Command 分流 ----
        if user_input.startswith("/"):
            result = handle_command(user_input, messages)
            if result is not None:
                print(result)
                continue
        # ---- 分流结束 ----

        messages.append({"role": "user", "content": user_input})
        response = run_agent(messages)
        messages.append({"role": "assistant", "content": response})
        print(f"\nAgent: {response}")
```

关键在 `continue`：命中 command 后，**不往 messages 里加任何东西**，直接回到等待用户输入。对 LLM 来说，这次交互根本没有发生过。

---

## 三、实现 Command Router

最朴素的 command router 就是一个字典映射：

```python
# ---- Command 定义 ----

def cmd_help(args, messages):
    return """可用命令：
  /help    - 显示本帮助
  /clear   - 清空对话历史
  /model   - 切换模型（如 /model gpt-4o）
  /compact - 压缩对话历史（保留要点）
  /status  - 显示当前状态"""

def cmd_clear(args, messages):
    messages.clear()
    messages.append({"role": "system", "content": SYSTEM_PROMPT})
    return "对话已清空。"

def cmd_model(args, messages):
    if not args:
        return f"当前模型：{os.environ.get('OPENAI_MODEL', 'gpt-4o-mini')}"
    os.environ["OPENAI_MODEL"] = args[0]
    return f"模型已切换为：{args[0]}"

def cmd_status(args, messages):
    msg_count = len(messages)
    model = os.environ.get("OPENAI_MODEL", "gpt-4o-mini")
    return f"消息数：{msg_count}  |  模型：{model}"

# ---- Command Router ----

COMMANDS = {
    "/help":    cmd_help,
    "/clear":   cmd_clear,
    "/model":   cmd_model,
    "/status":  cmd_status,
}

def handle_command(user_input, messages):
    parts = user_input.split()
    cmd = parts[0].lower()
    args = parts[1:]

    if cmd in COMMANDS:
        return COMMANDS[cmd](args, messages)
    return None   # 不认识的 / 开头输入，交给 run_agent 处理
```

一共 40 行左右。没有什么新概念，就是最基本的前缀匹配 + 字典分发。

注意 `handle_command` 返回 `None` 的情况：如果用户输入了 `/something_unknown`，我们不拦截，而是让 LLM 去处理——也许用户就是想和 Agent 讨论某个以 `/` 开头的路径。

---

## 四、/compact——最有意思的 Command

前面四个 command 都是纯本地操作，不需要 LLM 参与。但 `/compact` 不一样：

```python
def cmd_compact(args, messages):
    if len(messages) <= 4:
        return "对话太短，无需压缩。"

    # 取出需要压缩的旧消息
    system_msg = messages[0]
    old_messages = messages[1:-2]   # 保留最近 2 条
    recent = messages[-2:]

    # 让 LLM 做摘要——注意，这里调用了 LLM
    summary = llm.chat.completions.create(
        model=os.environ.get("OPENAI_MODEL", "gpt-4o-mini"),
        messages=[
            {"role": "system", "content": "请用中文简洁总结以下对话的要点，保留关键事实和决策。"},
            {"role": "user", "content": str(old_messages)}
        ]
    ).choices[0].message.content

    # 重建 messages
    messages.clear()
    messages.append(system_msg)
    messages.append({"role": "assistant", "content": f"[对话摘要] {summary}"})
    messages.extend(recent)

    return f"已压缩 {len(old_messages)} 条消息为摘要。当前消息数：{len(messages)}"
```

`/compact` 的特殊之处在于：**它是由 command 触发的，但内部还是要调 LLM。** 用户显式说"我要压缩"，但压缩这件事本身需要 LLM 来做摘要。

这打破了"command = 不过 LLM"的简单认知。更准确的理解是：

> **Command 的本质不是"不用 LLM"，而是"不走主循环"。**

主循环里，LLM 是决策者——它决定下一步做什么、用什么工具、什么时候停。而 `/compact` 里，LLM 只是一个被调用的工具——用户已经决定了要做什么（压缩），LLM 只负责执行摘要这个具体动作。

如果你读过第六篇（上下文压缩），会发现 `/compact` 做的事情和第六篇的自动压缩本质相同。区别在于**谁来触发**：第六篇是 Harness 自动触发（token 数超过阈值），这里是用户手动触发。两条路到同一个终点。

---

## 五、Command vs Tool vs LLM 自主决策

现在我们有三种"让 Agent 做事"的方式。什么时候该用哪种？

| | Command | Tool | LLM 自主决策 |
|--|---------|------|-------------|
| 谁触发 | 用户显式输入 `/xxx` | LLM 在主循环中自主调用 | LLM 自己判断 |
| 执行路径 | 绕过主循环，本地执行 | 在主循环内，LLM → function call → runtime | 纯 LLM 推理，不调外部 |
| 消耗 token | 不消耗（或极少） | 消耗 | 消耗 |
| 结果确定性 | 完全确定 | 工具执行确定，但 LLM 解读结果不确定 | 不确定 |
| 典型场景 | 清空上下文、切换模型、查看状态 | 读文件、搜索、执行代码 | 分析、推理、生成文本 |

一个判断原则：**如果一个操作的输入和输出都是确定的，不需要 LLM 的"理解"和"判断"，就做成 command。** 比如"清空对话"——不需要理解，不需要判断，执行就完了。

但边界不总是清晰的。拿 `/compact` 来说，它的触发是确定的（用户说了 `/compact`），但执行需要 LLM 参与。再比如"上下文快满了要不要压缩"——这件事也可以让 LLM 自己判断，但实践中发现用户显式控制（command）或 Harness 自动判断（第六篇的阈值机制）比让 LLM 自己决定更可靠。

---

## 六、Command 在真实产品中的样子

打开 Claude Code 或 OpenCode 这样的 CLI Agent，你会发现它们的 command 系统远不止 `/help` 和 `/clear`：

| Command | 作用 | 类型 |
|---------|------|------|
| `/help` | 显示帮助 | 纯本地 |
| `/clear` | 清空上下文 | 纯本地 |
| `/compact` | 压缩上下文 | 本地触发 + LLM 执行 |
| `/model` | 切换模型 | 纯本地 |
| `/mode` | 切换工作模式（如 architect / code） | 本地（修改 system prompt） |
| `/init` | 初始化项目 | 本地触发 + LLM 执行（生成 AGENTS.md） |
| `/review` | 代码审查 | 本地触发 + 注入预设 prompt + LLM 执行 |
| `/cost` | 显示 token 消耗 | 纯本地 |
| `/undo` | 撤销上一次文件修改 | 纯本地（git 操作） |

可以看到，command 在实际产品中承担了两类职责：

**第一类：环境控制。** `/clear`、`/model`、`/mode`、`/cost` 这些操作的对象是 Agent 的运行环境，不是用户的任务。LLM 不需要知道这些事。

**第二类：快捷入口。** `/init`、`/review` 本质上是"预设好的 prompt 模板 + 特定 tool 组合"。用户当然可以用自然语言说"帮我审查代码"，LLM 也能理解。但做成 command 的好处是：触发确定、行为一致、不会因为 LLM 理解偏差而跑偏。

---

## 七、和系列其他文章的关系

回顾一下 command 在整个 Agent 架构中的位置：

| 篇目 | 核心 | 和 Command 的关系 |
|------|------|-------------------|
| 第一篇：核心循环 | `run_agent` | Command 是 `run_agent` 的旁路 |
| 第三篇：MCP | 外部工具扩展 | MCP Tool 是 LLM 侧的能力扩展，Command 是用户侧的快捷入口 |
| 第六篇：上下文压缩 | 自动 compact | `/compact` 是手动版的第六篇 |
| 第七篇：安全防线 | Hook 机制 | Command 可以看作一种"入口 Hook"——在主循环之前拦截 |
| Harness 番外 | 模型之外的一切 | Command Router 是 Harness 的组成部分 |

用 Harness 番外的话说：**Command Router 就是 Harness 的一部分——它是模型之外的、让 Agent 真正能用的基础设施之一。**

---

## 八、总结

Command 不是什么高深的设计，就是一个前缀匹配 + 字典分发。但它背后的思维方式值得记住：

**Agent 的主循环是留给"需要思考的任务"的。** 不需要思考的操作——环境控制、状态查询、手动触发——应该绕过主循环，直接执行。

这是 Harness 工程的一部分：如何在 LLM 的智能和工程的确定性之间划出合理的边界。Command 选择了确定性的一边——用户说 `/clear` 就一定清空，不存在 LLM "理解错了"的可能。

一句话：**不是所有操作都要过大脑。**

---

*本文基于 agent-command.py 分析。完整 Agent 系列见 [GitHub 仓库](https://github.com/GitHubxsy/nanoAgent)。*
