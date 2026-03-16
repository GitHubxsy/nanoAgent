# 从零开始理解 Agent（二）：记忆与规划，206 行

> **「从零开始理解 Agent」系列** —— 通过一个不到 300 行的开源项目 [nanoAgent](https://github.com/sanbuphy/nanoAgent)，逐层拆解 OpenClaw / Claude Code 等 AI Agent 背后的全部核心概念。
>
> - [第一篇：底层原理，只有 103 行](./nanoAgent-01-essence.md) —— 工具 + 循环
> - **第二篇：记忆与规划**（本文）—— 206 行
> - [第三篇：Rules、Skills 与 MCP](./nanoAgent-03-rules-skills-mcp.md) —— 282 行
> - [第四篇：SubAgent](./nanoAgent-04-subagent.md) —— 192 行
> - [第五篇：多智能体团队](./nanoAgent-05-teams.md) —— 270 行
> - [第六篇：上下文压缩](./nanoAgent-06-compact.md) —— 169 行
> - [第七篇：安全防线](./nanoAgent-07-safety.md) —— 219 行

---

上一篇我们用 103 行代码实现了一个能干活的 Agent。但它有一个致命弱点：**金鱼记忆**。每次启动都是一张白纸，昨天做了什么、上一个任务的结果是什么——全部忘光。

这一篇，我们用 103 行额外的代码，给 Agent 装上两样东西：

1. **持久记忆（Memory）**：任务完成后自动保存，下次启动时自动加载
2. **任务规划（Planning）**：拿到复杂任务先拆解，再逐步执行

对应代码：[`agent-plus.py`](../agent-plus.py)（206 行）

---

## 一、为什么 Agent 需要记忆？

第一篇的 Agent 在单次运行中确实"有记忆"——`messages` 列表记录了整个行动轨迹。但这个记忆只存在于 Python 进程的内存里，程序一退出，`messages` 消失，一切归零。

这就导致一个现实问题：如果你让 Agent 帮你管理一个项目，今天它写了 `main.py`，明天你告诉它"继续昨天的工作"，它根本不知道昨天做了什么。

**真正的记忆需要持久化**——写到文件、数据库，或者任何能跨进程保存的地方。

---

## 二、持久记忆的实现：写文件就够了

`agent-plus.py` 用最简单的方案：把任务和结果以 Markdown 格式追加到 `agent_memory.md`。

```python
MEMORY_FILE = "agent_memory.md"

def save_memory(task, result):
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    entry = f"\n## {timestamp}\n**Task:** {task}\n**Result:** {result}\n"
    with open(MEMORY_FILE, 'a') as f:
        f.write(entry)

def load_memory():
    if not os.path.exists(MEMORY_FILE):
        return ""
    with open(MEMORY_FILE, 'r') as f:
        content = f.read()
        lines = content.split('\n')
        # 只取最近 50 行，避免 context 过长
        return '\n'.join(lines[-50:]) if len(lines) > 50 else content
```

加载时有一个关键设计：**只取最近 50 行**。原因是 LLM 的 context window 有限——如果把整个记忆文件都塞进去，几十次任务后就会超出限制。只保留最近的内容，保证记忆有用且不爆窗。

记忆加载后被注入到 `system_prompt`：

```python
memory = load_memory()
system_prompt = "You are a helpful assistant..."
if memory:
    system_prompt += f"\n\nPrevious context:\n{memory}"
messages = [{"role": "system", "content": system_prompt}]
```

**这就是记忆的本质：把过去的信息放进 system prompt，让 LLM "想起来"。**

---

## 三、任务规划：先想清楚再动手

当任务复杂时（比如"重构整个项目"），没有规划的 Agent 很容易迷失——东改一点、西改一点，最后改成一锅粥。

`agent-plus.py` 增加了一个 `create_plan` 函数，在执行前先把任务分解成 3-5 个步骤：

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
    # 解析返回的 JSON，得到步骤列表
    ...
    return steps
```

注意这里用了 `response_format={"type": "json_object"}`，强制 LLM 以 JSON 格式输出，避免解析失败。

有了步骤列表后，Agent 依次执行每个步骤，共用同一个 `messages` 上下文：

```python
def run_agent_plus(task, use_plan=False):
    memory = load_memory()
    messages = [{"role": "system", "content": system_prompt}]

    steps = create_plan(task) if use_plan else [task]

    for i, step in enumerate(steps, 1):
        print(f"\n[Step {i}/{len(steps)}] {step}")
        result, actions, messages = run_agent_step(step, messages)

    save_memory(task, final_result)
```

**关键：每个步骤共用同一个 `messages` 列表**。这意味着第 2 步能看到第 1 步做了什么，第 3 步能看到前两步的结果——这就是规划执行的"短期工作记忆"。

---

## 四、记忆 vs 规划：两种不同的时间维度

| 维度 | 记忆（Memory） | 规划（Planning） |
|------|----------------|------------------|
| 时间范围 | 跨任务、跨进程 | 单次任务内部 |
| 存储位置 | 文件（持久化） | messages 列表（临时） |
| 解决问题 | "上次做了什么" | "这次怎么分步做" |
| 触发条件 | 每次任务完成后自动保存 | 用 `--plan` 参数手动开启 |

```
时间轴
────────────────────────────────────────────────────▶

任务1                     任务2                     任务3
[规划→执行→保存记忆] ───▶ [加载记忆→规划→执行→保存] ───▶ ...
```

---

## 五、动手试一试

```bash
# 带规划的任务执行
python agent-plus.py --plan "找到所有 Python 文件，统计每个文件的行数，按行数排序，结果写入 report.txt"

# 第二次运行，Agent 会记得上次做过什么
python agent-plus.py "继续上次的工作，还有什么没完成的？"

# 查看记忆文件
cat agent_memory.md
```

运行后你会看到：
1. `[Planning]` 阶段输出拆解的步骤
2. `[Step N/M]` 逐步执行
3. `[Tool]` 日志显示每次工具调用
4. 任务结束后 `agent_memory.md` 新增一条记录

---

## 六、这一版还缺什么？

记忆和规划让 Agent 变得更"持续"和"有条理"，但还有两个痛点没解决：

1. **工具是固定的**：只有 bash / read_file / write_file，想加新工具还是得改代码
2. **没有行为规范**：Agent 依然可以做任何事，没有任何约束

这两个问题，在[第三篇](./nanoAgent-03-rules-skills-mcp.md)通过 Rules、Skills 和 MCP 来解决。

---

*本文基于 [sanbuphy/nanoAgent](https://github.com/sanbuphy/nanoAgent) 项目分析。*
