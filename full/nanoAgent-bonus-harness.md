# 从零开始理解 Agent（番外篇）：最近很火的 Harness 到底是什么？

> **「从零开始理解 Agent」系列番外** —— 如果你读过这个系列的七篇文章，恭喜你，你已经亲手搭过一个完整的 Harness 了。

最近 Agent 圈子里一个词突然火了起来：**Harness**。

回顾一下这几年的关键词演变：

- **2023-2024：Prompt Engineering** —— 研究怎么跟模型说话，让它回答得更好
- **2025：Context Engineering** —— 研究怎么组织上下文，让模型看到正确的信息
- **2026：Harness Engineering** —— 研究怎么搭建模型周围的整套系统，让模型真正能干活

每一次演变，关注点都在从"模型本身"向"模型之外"扩展。到了 Harness 这一步，视野已经不是一条 prompt 或一段上下文了，而是**工具、记忆、规划、安全、协作、压缩……整个基础设施**。

LangChain 团队成员 @Vtrivedy10 发了一个长帖，把这件事讲得极其清晰，核心论点只有一句话：

> **Agent = Model + Harness**

翻译过来就是：Agent 不是一个裸模型，而是"模型 + 外挂系统"。模型提供智能，Harness 提供让这种智能真正能干活的一切基础设施。

> Harness 这个词在英文中是"马具"的意思——套在马身上让它能拉车干活的那一整套装备。用在 Agent 语境下，意思就是"套在模型外面、让模型能真正干活的那一整套系统"。下文我们直接用 Harness 这个词，不做翻译。

如果你读过我们的七篇系列文章，你会发现——**你已经从零搭了一个完整的 Harness。** 只是当时我们没用这个词而已。

---

## 一、Harness 一句话解释

**Harness 就是除了模型本身之外的所有东西。**

裸模型（比如 GPT-4o、DeepSeek、Claude）能干什么？只能输入文本，输出文本。它不能：

- 执行代码
- 读写文件
- 记住上次对话
- 遵守你的项目规范
- 知道什么命令不能执行
- 把复杂任务拆给多个专家

**这些"不能"，全靠 Harness 来补。** Harness 不是一个具体的组件，而是一个总称——包裹在模型外面的所有代码、配置和执行逻辑，把模型的"智能"变成真正能干活的"工作引擎"。

用一个比喻：模型是一匹好马，Harness 是马鞍 + 马蹄铁 + 缰绳 + 道路 + 围栏。光有马跑不了运输，光有装备也没用，**两者结合才能真正干活。**

---

## 二、七篇文章 = 一个完整的 Harness

这是本文最核心的部分。我们把 Harness 的组成要素，逐一对应到系列文章中：

| Harness 组件 | 作用 | 对应系列文章 |
|-------------|------|------------|
| **工具 + 执行循环** | 让模型能执行代码、读写文件 | 第一篇：工具 + 循环 |
| **记忆 + 规划** | 让模型能记住过去、分步完成复杂任务 | 第二篇：记忆与规划 |
| **System Prompt + Rules + Skills + MCP** | 注入知识、约束行为、扩展工具 | 第三篇：Rules、Skills、MCP |
| **子 Agent 生成** | 把任务委派给专门的子智能体 | 第四篇：SubAgent |
| **多 Agent 编排** | 持久团队、通信通道、生命周期管理 | 第五篇：Teams |
| **上下文压缩 / Compaction** | 对抗 context window 限制 | 第六篇：上下文压缩 |
| **安全防线 + 执行钩子（Hook）** | 黑名单、用户确认、输出截断、可插拔管道 | 第七篇：安全与权限 |

**每一篇文章，都是在给 Harness 加一个组件。** 七篇加完，一个完整的 Harness 就搭好了。

---

## 三、用 Harness 的视角重新看七篇文章

### 第一篇 → Harness 的地基：工具 + 执行循环

裸模型只能输出文本。第一篇做的事情是：**给模型一双手。**

```python
# 这就是最小的 Harness
tools = [execute_bash, read_file, write_file]

for _ in range(max_iterations):        # 执行循环
    response = llm.call(messages, tools) # 模型输出意图
    if response.tool_calls:
        result = execute(tool_call)      # Harness 执行动作
        messages.append(result)          # 结果喂回模型
```

115 行代码，Harness 的核心骨架就在这里——**模型决策，Harness 执行，结果回传。** 所有后续组件都是在这个骨架上叠加。

### 第二篇 → Harness 的时间维度：记忆 + 规划

裸模型没有持久记忆，每次调用都是一张白纸。第二篇做的事情是：**给模型一个笔记本和一张地图。**

```python
# 记忆：Harness 负责存储和加载
memory = load_memory()  # 从文件读取历史
system_prompt += memory  # 注入到模型的输入中

# 规划：Harness 负责分步编排
steps = create_plan(task)  # 让模型先想后做
for step in steps:
    run_agent_step(step, messages)  # 逐步执行
```

注意：**模型本身没有"记住"任何东西**。是 Harness 在模型外面做了存储和加载，然后塞进 prompt 里"假装"模型有记忆。这就是 Harness 的本质——**用工程手段弥补模型的能力缺口**。

### 第三篇 → Harness 的知识注入：Rules + Skills + MCP

裸模型不知道你的项目规范、不知道生成 Word 文档的最佳实践、也无法调用 Slack API。第三篇做的事情是：**给模型一本规章制度、一套工作手册、一个可扩展的工具箱。**

```python
# Harness 从文件系统加载知识，注入到 system prompt
system_prompt = 基础指令 + Rules + Skills + Memory

# Harness 从配置文件动态加载工具
all_tools = base_tools + mcp_tools
```

这正是 Harness 理论中强调的：**System Prompts、工具描述、Skills 都是 Harness 的组成部分，不是模型的能力。**

### 第四篇 + 第五篇 → Harness 的协作层：SubAgent + Teams

裸模型是单线程的——一个模型实例，一个对话。第四、五篇做的事情是：**让 Harness 管理多个模型实例的创建、通信和生命周期。**

```python
# SubAgent：Harness 临时创建一个新的模型实例
def subagent(role, task):
    sub_messages = [{"role": "system", "content": f"You are a {role}"}]
    # 独立的循环，独立的上下文
    ...

# Teams：Harness 管理持久的多个模型实例
class Agent:
    def __init__(self, name, role):
        self.messages = [...]  # 持久记忆
        self.inbox = []        # 通信通道
```

模型不知道"还有其他 Agent 存在"。**是 Harness 在编排多个模型实例之间的协作。** 这就是 Harness 理论中说的"子 Agent 生成、切换、模型路由"。

### 第六篇 → Harness 对抗"上下文腐烂"

原帖中专门提到了一个概念：**Context Rot（上下文腐烂）**——随着对话越来越长，模型的性能会下降，关键信息被淹没在冗长的历史中。

第六篇做的事情正是 Harness 对抗 Context Rot 的核心手段：**Compaction（压缩）**。

```python
# Harness 在每轮循环前检查并压缩
messages = compact_messages(messages)
# 旧消息 → 摘要，最近消息 → 保留原样
```

原帖还提到了另外两种 Harness 手段：
- **Tool output offloading**：把大的工具输出存到文件里，prompt 中只留摘要
- **Skills 渐进加载**：不一次性把所有 Skill 塞进 prompt，按需加载

这些都是"上下文工程"——**不是让模型处理更长的文本，而是让 Harness 确保模型始终看到最重要的信息。**

### 第七篇 → Harness 的安全层：执行钩子

裸模型没有安全意识——它不知道 `rm -rf /` 的后果。第七篇做的事情是：**在模型和真实世界之间加一道安全网。**

```python
# Harness 的 Hook 管道
before_hooks = [check_blacklist, ask_confirmation]
after_hooks = [truncate_output]

def execute_with_hooks(tool_name, args, func):
    for hook in before_hooks:    # 执行前拦截
        blocked, msg = hook(tool_name, args)
        if blocked: return msg
    result = func(**args)        # 实际执行
    for hook in after_hooks:     # 执行后处理
        result = hook(tool_name, result)
    return result
```

原帖把这类机制称为"执行钩子"——压缩、续写、lint 检查、安全拦截，都是 Harness 在模型执行动作前后插入的控制逻辑。

### 补充：Ralph Loop —— 不让 Agent 半途而废的 Hook

原帖中还专门提到了一个有意思的机制：**Ralph Loop**。

回忆我们第一篇中的核心循环：

```python
for _ in range(max_iterations):
    ...
return "Max iterations reached"  # Agent 到达上限，退出
```

当 `max_iterations` 用完时，Agent 就停了——不管任务有没有完成。这在简单任务中没问题，但对于"自主写一个完整项目"这样的长时程任务，5 轮、10 轮根本不够。

Ralph Loop 的思路是：**在 Agent 即将退出时，Harness 拦截这个退出，检查任务是否真的完成了。如果没完成，重新注入一段提示让 Agent 继续干。**

用我们第七篇的 Hook 视角来理解，它就是一个 `before_exit_hook`：

```python
def ralph_loop_hook(messages, result):
    """Agent 想退出时，检查任务是否完成"""
    if result == "Max iterations reached":
        # 问 LLM：任务完成了吗？
        check = llm.call("Based on the conversation, is the task fully completed? Reply YES or NO.")
        if "NO" in check:
            # 没完成，注入续写提示，让 Agent 继续
            messages.append({"role": "user", "content": "任务还没完成，请继续。"})
            return False  # 不退出，继续循环
    return True  # 确实完成了，允许退出
```

本质就是把 `max_iterations` 从"硬上限"变成了"软检查点"——到了上限不是直接退出，而是先评估一下，没做完就续命。

这个机制配合文件系统（Agent 把中间结果写入文件，下次续写时读回来）和上下文压缩（防止续写时历史太长），就能让 Agent 持续工作数十轮甚至上百轮，完成真正复杂的任务。

---

## 四、一张图看清 Model vs Harness

```
┌─────────────────────────────────────────────────────┐
│                    Harness                            │
│                                                       │
│  ┌─────────────┐  ┌──────────┐  ┌────────────────┐  │
│  │ Rules       │  │ Skills   │  │ MCP Tools      │  │
│  │ (第三篇)    │  │ (第三篇)  │  │ (第三篇)       │  │
│  └──────┬──────┘  └────┬─────┘  └───────┬────────┘  │
│         └──────────────┼────────────────┘            │
│                        ▼                              │
│  ┌──── System Prompt + 工具列表 ────┐                │
│  │                                   │                │
│  │   Memory (第二篇)                 │                │
│  │   Compaction (第六篇)             │                │
│  │                                   │                │
│  └────────────┬──────────────────────┘                │
│               ▼                                       │
│  ┌─────────────────────────┐                         │
│  │      ┌─────────┐        │                         │
│  │      │  Model   │        │  ← 模型只管思考和决策   │
│  │      │ (裸模型)  │        │                         │
│  │      └─────────┘        │                         │
│  └────────────┬────────────┘                         │
│               ▼                                       │
│  ┌──── Hook 管道 (第七篇) ────┐                      │
│  │  黑名单 → 用户确认 → 执行   │                      │
│  └────────────┬───────────────┘                      │
│               ▼                                       │
│  ┌──── 工具执行层 (第一篇) ────┐                     │
│  │  bash / read / write / edit  │                     │
│  └────────────┬─────────────────┘                     │
│               ▼                                       │
│  ┌──── 协作层 (第四、五篇) ────┐                     │
│  │  SubAgent / Teams / 通信     │                     │
│  └──────────────────────────────┘                     │
│                                                       │
└─────────────────────────────────────────────────────┘
```

**模型在中间，Harness 在四周。** 模型只负责"想"，Harness 负责"让它能干活"——提供知识、提供工具、提供记忆、提供安全、提供协作、提供压缩。

---

## 五、为什么 Harness 这个概念重要？

### 5.1 它重新定义了"谁在决定 Agent 的好坏"

很多人以为 Agent 好不好用取决于模型。模型越强，Agent 越好。

**Harness 的视角说：不对。** 同一个模型，配上好的 Harness（好的工具、好的 Skill、好的压缩策略、好的安全机制）和差的 Harness，产出质量天壤之别。

这就是为什么 OpenClaw / Claude Code 用的模型大家都能调用，但产品体验完全不同——**差别在 Harness，不在 Model。**

### 5.2 它告诉你应该把精力花在哪

如果你在做 Agent 相关的工作：

- 你不是在训练模型 → **你就是在构建 Harness**
- 你写的 CLAUDE.md → 是 Harness 的一部分
- 你配的 MCP Server → 是 Harness 的一部分
- 你写的 Skill → 是 Harness 的一部分
- 你做的安全检查 → 是 Harness 的一部分

**Harness 工程永远不会消失。** 即使模型越来越强，它依然需要环境、工具、状态管理和安全防线。就像人类再聪明也需要办公室、电脑和公司制度一样。

### 5.3 它让"Agent 架构"有了一个统一的名字

在此之前，我们说"Agent 框架"、"Agent 基础设施"、"Agent 编排层"……各种叫法，边界模糊。

Harness 给了一个清晰的定义：**除了模型之外的一切，都是 Harness。** 简单、明确、好记。

---

## 六、回到我们的系列：你已经是 Harness 工程师了

如果你读完了「从零开始理解 Agent」的七篇文章，你已经亲手搭过：

- 工具执行层（第一篇）
- 记忆和规划系统（第二篇）
- 知识注入管道（第三篇）
- 子智能体调度（第四篇）
- 多智能体编排（第五篇）
- 上下文压缩引擎（第六篇）
- 安全防线和 Hook 管道（第七篇）

**这就是一个完整的 Harness。** 七篇文章，七个组件，组合在一起就是 `agent-full.py` 里的 507 行代码。

现在你知道了，这 507 行代码有一个更正式的名字：**Harness**。

```
Agent = Model + Harness
      = Model + 你写的那 507 行代码
```

---

*本文是「从零开始理解 Agent」系列的番外篇。完整系列：[第一篇](./nanoAgent-01-essence.md) → [第二篇](./nanoAgent-02-memory.md) → [第三篇](./nanoAgent-03-skills-mcp.md) → [第四篇](./nanoAgent-04-subagent.md) → [第五篇](./nanoAgent-05-teams.md) → [第六篇](./nanoAgent-06-compact.md) → [第七篇](./nanoAgent-07-safe.md) → 番外篇（本文）*
