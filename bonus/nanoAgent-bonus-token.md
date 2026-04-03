# 从零开始理解 Agent（番外篇）：Token 都花在哪了？

> **「从零开始理解 Agent」系列番外** —— 七篇正文里，我们从来没关心过一个问题：跑一次 Agent 到底消耗多少 Token？每轮循环花了多少？工具返回结果占了多大比例？这篇番外给 Agent 装上一个 Token 仪表盘，让消耗一目了然。

---

## 一、为什么要关心 Token？

用 Agent 和用普通对话最大的成本差异在于：**对话是一问一答，Agent 是一个循环。**

一次普通对话：1 次 API 调用，消耗一份 Token。

一次 Agent 任务：可能调用 5-15 次 API，每次调用都带着完整的 `messages` 历史，而且 `messages` 每轮都在增长——每调用一次工具，`messages` 至少新增两条（LLM 的回复 + 工具返回结果）。**输入 Token 是累积增长的，不是线性增长的。**

具体消耗多少，取决于工具返回结果的长度——`ls` 返回几行和 `cat` 一个千行文件，差距可以是几十倍。所以 Token 消耗不能靠估算，要靠实际测量。

---

## 二、API 返回的 usage 字段

好消息是，OpenAI 兼容的 API 每次调用都会返回 Token 使用情况：

```python
response = client.chat.completions.create(
    model=MODEL, messages=messages, tools=TOOLS
)

# response.usage 包含这三个字段：
# - prompt_tokens:     输入 Token 数（messages + tools schema）
# - completion_tokens: 输出 Token 数（LLM 的回复）
# - total_tokens:      两者之和
```

我们只需要在每轮循环中把这个数据收集起来。

---

## 三、给 Agent 加一个 Token 追踪器

在第一篇的 `agent.py` 基础上，只需要加一个简单的数据结构：

```python
class TokenTracker:
    """追踪 Agent 整个生命周期的 Token 消耗"""

    def __init__(self):
        self.rounds = []        # 每轮的详细数据
        self.total_input = 0
        self.total_output = 0

    def record(self, round_num, usage, message_count):
        """记录一轮循环的 Token 消耗"""
        input_tokens = usage.prompt_tokens
        output_tokens = usage.completion_tokens

        self.rounds.append({
            "round": round_num,
            "input": input_tokens,
            "output": output_tokens,
            "total": input_tokens + output_tokens,
            "messages": message_count
        })
        self.total_input += input_tokens
        self.total_output += output_tokens

    def summary(self):
        """打印消耗摘要"""
        print(f"\n{'='*50}")
        print(f"Token 消耗统计")
        print(f"{'='*50}")
        print(f"{'轮次':<6} {'输入':>8} {'输出':>8} {'合计':>8} {'消息数':>6}")
        print(f"{'-'*50}")
        for r in self.rounds:
            print(f"{r['round']:<6} {r['input']:>8} {r['output']:>8} "
                  f"{r['total']:>8} {r['messages']:>6}")
        print(f"{'-'*50}")
        print(f"{'合计':<6} {self.total_input:>8} {self.total_output:>8} "
              f"{self.total_input + self.total_output:>8}")
        print(f"{'='*50}")
```

嵌入 Agent 循环：

```python
def run_agent(user_message, max_iterations=10):
    tracker = TokenTracker()
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": user_message}
    ]

    for i in range(max_iterations):
        response = client.chat.completions.create(
            model=MODEL, messages=messages, tools=TOOLS
        )
        message = response.choices[0].message

        # 记录本轮消耗
        tracker.record(i + 1, response.usage, len(messages))

        if not message.tool_calls:
            tracker.summary()  # 任务结束时打印统计
            return message.content

        # 执行工具调用...
        messages.append(message)
        for tool_call in message.tool_calls:
            result = execute_tool(tool_call)
            messages.append({
                "role": "tool",
                "tool_call_id": tool_call.id,
                "content": result
            })

    tracker.summary()
    return "Max iterations reached"
```

---

## 四、实际输出长什么样

需要说明的是，不同任务的 Token 消耗差异很大——一个"创建 hello.py"可能 2 轮就结束，一个"重构整个项目"可能跑 20 轮。下面的数据只是一个具体案例，目的是让大家对 Agent 的 Token 消耗有个感性认识，而不是一个通用基准。

让 Agent 执行"找到当前目录的 Python 文件，统计行数，写入报告"，Token 追踪器的输出类似这样（以下为示意数据，实际数值因模型和任务而异）：

```
==================================================
Token 消耗统计
==================================================
轮次     输入     输出     合计   消息数
--------------------------------------------------
1         523      87      610      2
2        1204     103     1307      5
3        2891      76     2967      8
4        3542      45     3587     11
5        3870     156     4026     13
--------------------------------------------------
合计    12030     467    12497
==================================================
```

几个一眼就能看出的规律：

**输入 Token 逐轮递增。** 第 1 轮 523，第 5 轮 3870——因为每轮都要把完整的 `messages` 历史发给 LLM，历史越长输入越大。

**输出 Token 相对稳定。** 每轮只有几十到一两百——LLM 的回复通常就是一段思考 + 一次工具调用的 JSON。

**输入远大于输出。** 在这个示例中，输入占了总消耗的绝大部分。这在 Agent 场景中是普遍规律——意味着**降低成本的关键是控制输入，不是控制输出。**

---

## 五、Token 都花在哪了？

输入 Token 可以拆成三部分：

```
输入 Token = system prompt（含 Skills）+ tools schema + 历史 messages
```

其中：

**system prompt** 每轮都要带，固定成本。如果只有基础指令，通常几百 Token。但回忆第三篇——Rules 和 Skills 的内容都是注入到 system prompt 中的。一旦挂载了几个 Skill（每个 Skill 的描述可能几百到上千 Token），system prompt 就会从几百膨胀到几千甚至上万。这是一个容易被忽略的固定开销：**每一轮 API 调用都要重复发送全部 Skill 描述。**

**tools schema** 也是每轮都要带。nanoAgent 的三个工具（read_file、write_file、execute_bash），JSON Schema 大约几百 Token（具体取决于参数描述的详细程度）。但这是最简情况。生产级 Agent 动辄注册十几个甚至几十个工具，每个工具的参数描述、枚举值、嵌套结构都会占 Token。工具数量增长十倍，tools schema 的开销也会相应增长——而且这个成本每轮都要付。这也是为什么第三篇的 MCP 动态加载工具、而不是把所有工具都塞进去的原因之一：**按需加载，用不到的工具不注册，省的是每一轮的固定税。**

**历史 messages** 这是大头，也是唯一会增长的部分。增长速度取决于工具返回结果的长度——`ls` 返回几行，`cat` 一个大文件可能返回几千行。

总结一下：system prompt（含 Skills）和 tools schema 是"固定税"，每轮都交；历史 messages 是"累进税"，越跑越多。降本要两手抓——减少固定税（精简 Skill 数量与描述、精简工具）和控制累进税（截断输出、及时压缩）。

---

## 六、和第六篇压缩的关系

现在回头看第六篇的上下文压缩，它做的事情就清楚了：**砍掉历史 messages 中的旧内容，降低每轮的输入 Token。**

没有压缩时，Token 消耗曲线是这样的：

```
输入 Token
    ^
    |          /
    |        /
    |      /       ← 越来越贵
    |    /
    |  /
    |/
    +------------→ 轮次
```

有压缩时：

```
输入 Token
    ^
    |    /\  /\
    |   /  \/  \   ← 锯齿形，有上限
    |  /
    | /
    |/
    +------------→ 轮次
```

压缩把一条单调递增的曲线变成了有上限的锯齿波。Token 追踪器加上压缩，你就能精确看到每次压缩省了多少 Token。

在 `TokenTracker` 中加一行标记压缩事件：

```python
def record_compaction(self, round_num, before_tokens, after_tokens):
    """记录一次压缩事件"""
    saved = before_tokens - after_tokens
    print(f"  [压缩] 轮次 {round_num}: {before_tokens} → {after_tokens} "
          f"(节省 {saved} tokens, {saved/before_tokens*100:.0f}%)")
```

---

## 七、几条实用的成本控制经验

有了 Token 追踪器之后，一些优化方向会变得很直观：

**截断工具输出。** 第七篇安全篇里已经做了输出截断（`MAX_OUTPUT_LENGTH`），它不只是为了安全，也是成本控制的第一道防线。`cat` 一个 10000 行的文件会让后续每一轮都多带 10000 行的历史——截断到前 200 行，后续每轮都能省下大量输入 Token。

**减少不必要的工具调用。** 有时 LLM 会先 `ls` 看一下目录，再 `cat` 某个文件，再 `grep` 搜索内容——而实际上一条 `grep -r "keyword" .` 就能搞定。更好的 system prompt 可以引导 LLM 用更少的步骤完成任务。

**清理不用的 MCP 和 Skill。** 第五节讲了，tools schema 和 Skill 描述是每轮都要付的"固定税"。注册了 10 个 MCP 工具但日常只用 3 个，剩下 7 个的 schema 每轮都在白白消耗 Token。Skill 同理——挂载了五个 Skill 但当前任务只涉及其中一个，其余四个的描述都是浪费。定期审视已注册的 MCP 和 Skill，删掉不用的，是最简单的降本手段。

**选对模型。** 简单任务（文件操作、格式转换）用便宜的小模型，复杂任务（代码重构、架构分析）用贵的大模型。这就是为什么有些 Agent 框架支持"模型路由"——根据任务复杂度自动选模型。

**及时压缩。** 第六篇的压缩阈值不要设太高。阈值越高，压缩前的几轮输入 Token 越大。根据 Token 追踪器的数据调整阈值，找到"压缩频率"和"摘要质量"之间的平衡点。

---

## 八、小结

Token 追踪器的代码量很少，但它把一个黑盒变成了白盒——Agent 每轮花了多少、花在哪了、哪里可以省，全都看得见。

回到 Harness 番外篇的视角：Token 追踪是 Harness 的"仪表盘"。没有它，你只知道"任务完成了"，但不知道 Agent 用了几轮、每轮输入多少 Token、哪一轮因为工具返回了大量内容导致消耗飙升。有了它，这些问题都有了数据支撑，优化才有方向。

---

*「从零开始理解 Agent」系列番外。正文第六篇讲了怎么压缩 Token，这篇讲怎么看清 Token 花在哪了。*
