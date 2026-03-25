# 从零开始理解 Agent（番外篇）：谁来创建 Agent？主 Agent 创建 vs 用户创建的两种模式

> 在系列第五篇中，我们实现了多智能体团队——由**编排代码在运行时动态创建** Agent。但在实际产品中，还有另一种常见模式：**由用户在运行前手动创建**多个 Agent，然后由主 Agent 调度它们协作。
>
> 这两种模式的适用场景完全不同。本文继续用"开发一个 TODO 应用"的案例，用代码对比拆解它们的差异。

-----

## 一、先回忆：第五篇中的 Teams 是怎么工作的？

第五篇的核心代码是这样的：

```python
class Team:
    def hire(self, name, role):
        self.agents[name] = Agent(name, role)

# 主 Agent 在运行中决定创建谁
team.hire("alice", "frontend developer")
team.hire("bob", "backend developer")
team.hire("carol", "code reviewer")
```

关键点：**谁来决定创建哪些 Agent？是主 Agent（或编排代码）在运行时决定的。** 用户只说了"帮我创建一个 TODO 应用"，至于需要几个 Agent、每个 Agent 负责什么，都是系统自动决定的。

这种模式可以叫做**"运行时编排"**——Agent 的组成是动态的，根据任务需要临时组建。

-----

## 二、另一种模式：用户预设 Agent

但在很多实际场景中，Agent 不是临时创建的，而是**用户提前定义好的**。

还是 TODO 应用的例子。假设你是一个团队负责人，你知道项目一直需要前端、后端、测试三个角色。你不想每次都让系统临时拉人，而是**提前把三个 Agent 定义好，让它们长期待命**，由主 Agent 根据需要调度：

```python
# 用户提前定义三个专家 Agent
agents_config = {
    "前端 Agent": {
        "role": "负责 TODO 应用的 React 前端页面",
        "tools": ["write_file", "read_file", "bash"],
    },
    "后端 Agent": {
        "role": "负责 TODO 应用的 Python API 后端",
        "tools": ["write_file", "read_file", "bash", "execute_sql"],
    },
    "测试 Agent": {
        "role": "负责编写和运行测试用例",
        "tools": ["read_file", "bash", "pytest"],
    },
}
```

这种模式可以叫做**"预设编排"**——Agent 的组成是固定的，由用户在运行前定义好，运行时由主 Agent 按需调度。

-----

## 三、两种模式的核心差异

|              |运行时编排（第五篇）   |预设编排（本文）          |
|--------------|-------------|------------------|
|**谁创建 Agent？**|主 Agent 或编排代码|用户                |
|**何时创建？**     |运行时，根据任务动态创建 |运行前，提前配置好         |
|**Agent 数量**  |不确定，按需生成     |固定，用户决定           |
|**Agent 的角色** |由任务决定        |由用户决定             |
|**Agent 的工具** |通常共享同一套工具    |每个 Agent 可以有不同的工具集|
|**生命周期**      |任务完成后可销毁     |长期存活，跨任务保持记忆      |
|**适用场景**      |一次性复杂任务      |持续迭代的项目           |

用 TODO 应用来类比：

- **运行时编排** = 你说"帮我做一个 TODO 应用"，系统临时决定需要前端、后端、测试三个人，项目做完就解散
- **预设编排** = 你提前定义好前端 Agent、后端 Agent、测试 Agent，它们长期待命，每次有需求由主 Agent 分配给对应的人

-----

## 四、代码实现：用户预设 Agent

### 4.1 Agent 定义：增加独立工具集

第五篇的 Agent 只有 name、role、messages、inbox。用户预设模式需要增加**独立的工具集**：

```python
class Agent:
    def __init__(self, name, role, tools=None):
        self.name = name
        self.role = role
        self.tools = tools or []       # 每个 Agent 有自己的工具集
        self.messages = [{"role": "system", "content": f"You are {name}, a {role}. Be concise."}]
        self.inbox = []

    def receive(self, sender, message):
        self.inbox.append({"from": sender, "content": message})

    def chat(self, task):
        """处理收件箱 → 调用 LLM → 返回结果"""
        if self.inbox:
            inbox_text = "\n".join(f"[From {m['from']}]: {m['content']}" for m in self.inbox)
            self.messages.append({"role": "user", "content": f"Messages:\n{inbox_text}\n\nTask: {task}"})
            self.inbox.clear()
        else:
            self.messages.append({"role": "user", "content": task})

        reply = CLIENT.chat.completions.create(model=MODEL, messages=self.messages).choices[0].message.content
        self.messages.append({"role": "assistant", "content": reply})
        return reply
```

> **进一步扩展：不同 Agent 可以使用不同的大模型。** 上面的代码中所有 Agent 共享同一个 `CLIENT` 和 `MODEL`，但实际场景中完全可以给每个 Agent 配置不同的模型。比如前端 Agent 用擅长快速生成 UI 的 Gemini，后端 Agent 用擅长代码质量的 Claude，测试 Agent 用擅长代码推理的 Codex。只需要在 `__init__` 中加一个 `model` 参数：
>
> ```python
> class Agent:
>     def __init__(self, name, role, tools=None, model=None):
>         self.model = model or MODEL  # 可以为每个 Agent 指定不同的模型
>         ...
>
> reg.register("前端 Agent", "React 前端", tools=[...], model="gemini-2.5-pro")
> reg.register("后端 Agent", "Python API",  tools=[...], model="claude-sonnet-4-20250514")
> reg.register("测试 Agent", "测试用例",    tools=[...], model="codex-mini")
> ```
>
> 这也是预设编排相比 SubAgent 的又一个优势——每个 Agent 不仅有独立的工具集和记忆，还可以有独立的模型选择，实现**成本和能力的精细化配置**。

### 4.2 AgentRegistry：用户注册 Agent

第五篇的 Team 类由代码创建 Agent。用户预设模式需要一个**注册表**，让用户自己定义：

```python
class AgentRegistry:
    def __init__(self):
        self.agents = {}

    def register(self, name, role, tools=None):
        self.agents[name] = Agent(name, role, tools)
        print(f"  [Registry] ✅ {name}")

    def unregister(self, name):
        del self.agents[name]

    def get(self, name):
        return self.agents.get(name)

    def list_agents(self):
        return [(n, a.role) for n, a in self.agents.items()]
```

-----

## 五、主 Agent 调用已注册 Agent

Agent 注册好了，怎么用？**把已注册的 Agent 包装成主 Agent 的一个工具，让 LLM 自己决定该找谁干活。**

比如用户说"帮我给 TODO 应用加一个截止日期功能"——这既需要前端改界面、也需要后端改接口。主 Agent 理解意图后，从已注册的 Agent 中选择合适的来执行。

### 5.1 核心实现：delegate 工具

```python
def run_main_agent(task, registry, max_iterations=5):
    agent_names = [n for n, _ in registry.list_agents()]
    delegate_tool = {"type": "function", "function": {
        "name": "delegate",
        "description": f"Delegate a task to a specialist agent. Available: {', '.join(agent_names)}",
        "parameters": {"type": "object", "properties": {
            "agent_name": {"type": "string", "description": f"One of: {', '.join(agent_names)}"},
            "task":       {"type": "string", "description": "Task to delegate"}
        }, "required": ["agent_name", "task"]}
    }}
    messages = [
        {"role": "system", "content": "You are a main agent. Delegate tasks to specialist agents. Be concise."},
        {"role": "user", "content": task},
    ]
    for _ in range(max_iterations):
        msg = CLIENT.chat.completions.create(
            model=MODEL, messages=messages, tools=[delegate_tool]).choices[0].message
        messages.append(msg)
        if not msg.tool_calls:
            return msg.content
        for tc in msg.tool_calls:
            args = json.loads(tc.function.arguments)
            agent = registry.get(args["agent_name"])
            result = agent.chat(args["task"]) if agent else f"Agent not found: {args['agent_name']}"
            messages.append({"role": "tool", "tool_call_id": tc.id, "content": result})
    return "Max iterations reached"
```

### 5.2 完整流程

```python
# 1. 用户注册 Agent
reg = AgentRegistry()
reg.register("前端 Agent", "负责 TODO 应用的 React 前端", tools=["write_file", "read_file", "bash"])
reg.register("后端 Agent", "负责 TODO 应用的 Python API",  tools=["write_file", "read_file", "bash"])
reg.register("测试 Agent", "编写和运行测试用例",           tools=["read_file", "bash", "pytest"])

# 2. 用户对主 Agent 说话，主 Agent 自己决定委派给谁
print(run_main_agent("帮我给 TODO 应用加一个截止日期功能", reg))
```

主 Agent 收到请求后的"思考过程"：

```
用户: "帮我给 TODO 应用加一个截止日期功能"
  → 主 Agent 分析：这个功能需要后端加字段 + 前端加 UI
  → 主 Agent 决定: delegate(agent_name="后端 Agent", task="给 TODO 模型增加 deadline 字段，更新 API")
  → 后端 Agent 开始工作...
  → 返回结果后，主 Agent 继续: delegate(agent_name="前端 Agent", task="在 TODO 列表中显示截止日期，增加日期选择器")
  → 前端 Agent 开始工作...
  → 最后: delegate(agent_name="测试 Agent", task="测试截止日期功能是否正常")
  → 主 Agent 汇总结果返回给用户
```

### 5.3 和 SubAgent 的关键区别

|         |SubAgent（第四篇）         |调用已注册 Agent（本文）             |
|---------|----------------------|----------------------------|
|Agent 从哪来|临时创建                  |用户预先注册                      |
|有持久记忆吗   |❌ 用完就消亡               |✅ 记得之前的对话                   |
|有专属工具吗   |❌ 和主 Agent 共享         |✅ 每个 Agent 有自己的工具集          |
|谁决定调用    |LLM（和 SubAgent 一样）    |LLM（和 SubAgent 一样）          |
|本质       |`subagent(role, task)`|`delegate(agent_name, task)`|

用 TODO 应用来说明：SubAgent 模式下，每次你说"帮我做前端"，系统都临时创建一个全新的前端 Agent，它不知道之前做过什么。delegate 模式下，前端 Agent 一直在，它记得上次做了哪些页面、用了什么组件库，第二次交代任务时不需要重复说明上下文。

-----

## 六、持久记忆的价值

这是预设编排最大的优势——**Agent 跨任务保持记忆**。

```python
# 第一次：加 TODO 列表功能
print(run_main_agent("帮 TODO 应用实现添加和删除功能", reg))

# 前端 Agent 的 messages 已经累积了第一次的对话历史

# 第二次：加截止日期功能
print(run_main_agent("帮 TODO 应用加一个截止日期功能", reg))
# 前端 Agent 记得第一次用了 React + Ant Design
# 不需要重复说明技术栈
```

如果用 SubAgent（第四篇），每次都是全新的 Agent，第二次任务时它不知道第一次用了什么技术栈，可能会换一套完全不同的方案。

如果用预设 Agent（本文），前端 Agent 的 `self.messages` 累积了所有历史对话，它知道"上次用了 React + Ant Design"，会自然延续同一套方案。

**这就是 `messages` 从局部变量到实例属性的实际价值。** 第五篇讲的是原理（数据放哪决定生命周期），本文展示的是效果（持久记忆带来的一致性）。

-----

## 七、两种编排模式的架构对比

```
运行时编排（第五篇）:

  用户: "创建一个 TODO 应用"
    │
    ▼
  主 Agent / 编排代码
    ├── hire("alice", "frontend developer")  ← 动态决定
    ├── hire("bob", "backend developer")     ← 动态决定
    └── hire("carol", "code reviewer")       ← 动态决定
    │
    ▼
  Team.send() / Team.broadcast()             ← 主 Agent 调度

预设编排（本文）:

  用户: 提前注册三个 Agent
    ├── register("前端 Agent")   ← 用户决定
    ├── register("后端 Agent")   ← 用户决定
    └── register("测试 Agent")   ← 用户决定
    │
    ▼
  用户: "帮 TODO 应用加截止日期功能"
    │
    ▼
  主 Agent → delegate("后端 Agent", ...)     ← LLM 选择
           → delegate("前端 Agent", ...)     ← LLM 选择
           → delegate("测试 Agent", ...)     ← LLM 选择
```

-----

## 八、什么时候用哪种？

|场景                |推荐模式 |原因                      |
|------------------|-----|------------------------|
|"帮我从零写一个 TODO 应用" |运行时编排|不确定需要几个人，让系统决定          |
|"帮 TODO 应用加截止日期功能"|预设编排 |前端/后端/测试 Agent 已就位，有历史记忆|
|"复杂重构，角色不确定"      |运行时编排|需要动态调整角色和分工             |
|"日常迭代开发"          |预设编排 |Agent 记得之前的技术栈和上下文      |
|"一次性任务，做完就走"      |运行时编排|不需要持久记忆                 |
|"长期项目，反复迭代"       |预设编排 |需要跨任务的一致性               |

**简单判断标准：**

- 任务是**一次性的、不确定需要谁** → 运行时编排
- 任务是**持续迭代的、团队固定** → 预设编排

-----

## 九、代码差异总结

|组件      |运行时编排（第五篇）                |预设编排（本文）                              |
|--------|--------------------------|--------------------------------------|
|Agent 创建|`team.hire(name, role)`   |`registry.register(name, role, tools)`|
|任务分发    |`team.send(from, to, msg)`|主 Agent `delegate(agent_name, task)`  |
|工具集     |所有 Agent 共享               |每个 Agent 独立配置                         |
|谁决定调用谁  |主 Agent / 编排代码            |LLM 自己决定                              |
|新增 Agent|改代码                       |改配置（不需要改代码）                           |
|核心新概念   |Team 类                    |**AgentRegistry + delegate**          |

本文新增了两个概念：

- **AgentRegistry**：用户注册和管理 Agent 的地方（类似"HR 系统"——记录公司有哪些人）
- **delegate**：主 Agent 调用已注册 Agent 的工具（类似"项目经理"——分析需求后分配给对应的人）

-----

## 十、和系列其他篇的关系

|篇           |关键概念                 |TODO 应用中的类比                              |
|------------|---------------------|-----------------------------------------|
|第四篇 SubAgent|一次性临时工               |临时找个人帮忙写个页面，写完就走                         |
|第五篇 Teams   |持久团队，主 Agent 创建      |临时组个项目组做 TODO 应用，做完解散                    |
|**本文**      |**用户预设 + 主 Agent 委派**|**前端/后端/测试三个 Agent 长期待命，有需求就干活，记得之前做过什么**|

三者是递进关系：

- **SubAgent** → 临时叫一个人帮忙（用完就走，不记得你）
- **Teams** → 临时组建一个项目组（项目结束就解散）
- **预设编排** → 你的固定团队（长期存在，记得所有历史，越合作越默契）

越往后，Agent 的生命周期越长、记忆越丰富、协作效率越高。

-----

*本文是「从零开始理解 Agent」系列的番外篇。完整系列见 [GitHub 仓库](https://github.com/GitHubxsy/nanoAgent)。*
