# 从零开始做 Multi-Agent 系统（一）：什么时候单 Agent 不够

> **「从零开始做 Multi-Agent 系统」系列** —— 前三部讲"理解"，这一部讲"做"。我们围绕同一个 demo 项目（自动化技术调研助手），从单 Agent baseline 开始，每章往多 Agent 方向多走一步，最后回头算账，看哪些步是真的赚了、哪些是"沟通税"。
>
> - **第一篇：什么时候单 Agent 不够**（本文）
> - [第二篇：最小多 Agent 骨架](../02-minimum-skeleton/multi-agent-02-minimum-skeleton.md)
> - [第三篇：Agent 之间怎么传话](../03-communication/multi-agent-03-communication.md)
> - [第四篇：编排模式之争](../04-orchestration/multi-agent-04-orchestration.md)
> - [第五篇：状态、记忆与上下文](../05-state-memory/multi-agent-05-state-memory.md)
> - [第六篇：错误传播、重试与可观测性](../06-failure-trace/multi-agent-06-failure-trace.md)
> - [第七篇：边界与反模式](../07-boundaries/multi-agent-07-boundaries.md)

---

## 一、先说结论

| 你以为的 | 实际的 |
|---------|-------|
| 多 Agent 是"更高级的单 Agent" | 多 Agent 是对一类特殊场景的针对性设计 |
| 单 Agent 做不好，换多 Agent 就行 | 80% 的"做不好"是工具或 prompt 没设计好 |
| 多 Agent 更快更强 | 多 Agent 通常贵 3–5 倍 token，调试更难 |
| 框架越强，效果越好 | 在错误场景上用多 Agent，只会更贵更慢 |

一句话总结：**只有"可并行 + 多视角 + 上下文需隔离"三个条件同时满足，多 Agent 才真的赢**。本篇先用单 Agent 做一遍 baseline，让你亲眼看到它到底在哪翻车。

---

## 二、本系列的 demo：自动化技术调研助手

整个系列围绕一个具体场景：**输入一个技术问题，输出一份研究报告**。

> **输入**：「对比 FlashAttention、PagedAttention、SGLang、vLLM、TensorRT-LLM 在长上下文场景的优劣」
>
> **期望输出**：一份 ~2000 字的对比报告，覆盖核心思路、适用场景、性能数据，最后给出推荐。

选这个任务有四个理由：

1. **够大**——5 个方案 × 4 个维度，单 Agent 不一定装得下
2. **可并行**——5 个方案之间没有依赖，可以同时调研
3. **需要多视角**——光"搜"不够，还需要"批判"和"整合"
4. **失败模式真实**——信息冲突、引用过时、报告头重脚轻，都很容易出现

---

## 三、单 Agent baseline：先跑一遍

在拆多 Agent 之前，**先用最简单的方式跑一遍**。这是这个系列和市面上多 Agent 教程的最大差别——我们先做 baseline，再决定要不要加架构。

### 3.1 代码结构

配套代码在 [multi-agent-01-when-single-agent-fails.py](./multi-agent-01-when-single-agent-fails.py)，核心不到 60 行：

```python
# 三个工具
tools = [web_search, web_read, write_file]

# 一段 system prompt
SYSTEM_PROMPT = """你是一个技术调研助手。用户给你一个技术问题，你需要：
1. 用 web_search 找相关资料
2. 用 web_read 读取关键页面
3. 综合信息写一份对比报告（约 2000 字）
4. 用 write_file 保存到 work/report-single.md
"""

# Agent 循环——和第一部 Agent 系列的核心循环一模一样
for i in range(max_iters):
    msg = client.chat.completions.create(model=MODEL, messages=messages, tools=tools)
    if not msg.tool_calls:       # 模型不再调用工具 → 任务完成
        break
    for tc in msg.tool_calls:    # 执行工具，结果追加到 messages
        result = FUNCTIONS[tc.function.name](**args)
        messages.append({"role": "tool", ...})
```

> 如果你读过 [Agent 系列第一篇](../../agent/01-essence/agent-essence.md)，会发现这就是那个"LLM → 检查 tool_calls → 执行工具 → 回填 messages"的循环。唯一的区别是工具从 `execute_bash` / `read_file` 换成了 `web_search` / `web_read`。

### 3.2 跑起来

```bash
OPENAI_API_KEY=... python multi-agent-01-when-single-agent-fails.py
```

> 脚本内置了 mock 工具（返回伪造的搜索结果），不需要真实搜索 API，任何 OpenAI 兼容模型都能跑。

### 3.3 运行观察

把 GPU 推理优化的问题丢给它，观察循环：

```text
[Round 1] web_search(["query"])        → 返回 2 条结果 (~1K tokens)
[Round 2] web_search(["query"])        → 返回 2 条结果 (~1K tokens)
[Round 3] web_search(["query"])        → 返回 1 条结果
[Round 4] web_read(["url"])            → 论文正文 ~8K tokens
[Round 5] web_read(["url"])            → 博客正文 ~8K tokens
[Round 6] web_read(["url"])            → 文档 ~8K tokens
...
[Round 12] 上下文已用 ~80K，准备写报告
[Round 13] write_file(["path","content"])  → 输出报告
```

报告写出来了。但仔细看，问题就开始浮现。

---

## 四、四个翻车点

### 翻车点 1：Context 爆炸

到 Round 12 时，上下文已经塞了 80K tokens——其中 90% 是搜索结果和文章正文。模型最后写报告时，**早期读到的内容已经被注意力稀释**，写出来的内容偏向最后读的几篇。

具体表现：报告里 PagedAttention 写得最详细（因为最后读的），FlashAttention 明显单薄，TensorRT-LLM 几乎一笔带过。

### 翻车点 2：串行慢

5 个方案，模型一个一个搜——`FlashAttention` 搜完搜 `PagedAttention`，再搜 `SGLang`。每次搜索 + 读取需要一轮循环，串行累积，**总耗时比预期长很多**。

而这些搜索之间没有依赖关系——FlashAttention 怎么样和 PagedAttention 怎么样是两件独立的事，**完全可以并行**。但单 Agent 的循环天然是串行的——一次一个工具调用，等结果回来再决定下一步。

### 翻车点 3：视角单一

报告里出现了这样的情况：

> "FlashAttention 在长上下文场景下性能最好，比 PagedAttention 快 2.3 倍。"

这句话来自 FlashAttention 团队自己的博客。但另一篇文章里又说"PagedAttention 比 FlashAttention 快 1.8 倍"——**两篇观点对立，模型同时引用，没察觉到冲突**。

问题出在：模型没有"批判"这一步。它把读到的内容直接整合，没人质疑信息的可信度、时效性、立场偏差。

### 翻车点 4：任务边界乱

system prompt 把"搜索"、"阅读"、"对比"、"判断"、"写作"五件事混在一起。模型每一轮都在切换角色——搜索、阅读、判断、写报告交替进行。

代价是：
- 注意力分散，每一项都做不深
- 出错了不知道是哪一步出的（搜得不全？读漏了？整合错了？）
- 加新功能（比如"加一个 critic"）会让 prompt 进一步膨胀

---

## 五、这是工具问题、prompt 问题，还是架构问题？

到这里，一个公允的反问是：

> "这些问题真的是单 Agent 的问题吗？换个更好的工具、写个更好的 prompt，是不是就行了？"

值得认真回答这个问题。**很多看起来"需要多 Agent"的场景，本质上是工具或 prompt 没设计好**。

### 5.1 Context 爆炸

**部分能解**。把搜索结果做摘要、把网页内容做压缩，能降低 context 占用。但根本解不掉——只要方案数量继续涨（10 个、20 个），单 Agent 的 context 总会被填满。

### 5.2 串行慢

**几乎解不了**。单 Agent 的循环天然是串行的。虽然 OpenAI 支持 parallel tool calls（一次返回多个工具调用），但结果回来后还是在同一个 context 里串行处理。

### 5.3 视角单一

**勉强能，代价大**。你可以在 prompt 里加"写报告前先批判每条信息"。但效果有限——**同一个模型在同一个 context 里"自我批判"，它已经被自己读到的内容洗脑了**。让一个独立的 critic 来批判，效果完全不同——但那已经是多 Agent 了。

### 5.4 任务边界乱

**能改善，不能根治**。把 prompt 写得结构化——"先搜索，搜够了再读，读够了再写"——能减轻问题。但模型不会严格遵守，它可能写到一半发现遗漏，回去搜索，而此时 context 已经塞了 80K 内容了。

### 5.5 小结

| 翻车点 | 工具/prompt 能解吗 | 多 Agent 能解吗 |
|--------|-------------------|----------------|
| Context 爆炸 | 部分能 | 能（每个 Agent 独立 context） |
| 串行慢 | 几乎不能 | 能（worker 并行） |
| 视角单一 | 勉强能 | 能（独立的 critic） |
| 任务边界乱 | 能改善不能根治 | 能（每个 Agent 单一职责） |

> **关键洞察**：4 个翻车点里，2 个是真正的架构问题（context 爆炸 + 串行慢），1 个 prompt 解不彻底（视角单一），1 个 prompt 能改善但不优雅（任务边界）。判断"该不该上多 Agent"的核心标准——**问题是不是真的来自架构，而不是工程惰性**。

---

## 六、多 Agent 能解什么、解不了什么

开始拆多 Agent 之前，先打个预防针：**多 Agent 不是免费的**。它会带来一组新的问题：

| 新问题 | 具体表现 |
|-------|---------|
| 通信成本 | Agent 之间传数据要花 token |
| 状态一致性 | 3 个 worker 都搜了同一篇论文怎么办 |
| 错误传播 | 一个 worker 跑挂了，整个系统怎么办 |
| 调试地狱 | 5 个 Agent 各跑各的，出问题了去哪查 |

所以正确的姿势是：**只在多 Agent 真正赢的场景用它**。

经验上，多 Agent 真的赢需要三个条件**同时**满足：

| 条件 | 含义 | 只满足 1 个 |
|------|------|-----------|
| 任务可并行 | 子任务之间没有依赖，能真的同时跑 | 多半是 prompt 没写好 |
| 视角需要多样 | 需要不同立场的 Agent 互相校验 | 试试单 Agent + SubAgent |
| 上下文需要隔离 | 每个子任务的上下文都很大，塞一起会爆 | 三个都满足才需要常驻多 Agent |

回到我们的 demo——GPU 推理优化调研：

1. ✅ 5 个方案并行可调研
2. ✅ 需要 critic 视角避免引用过时
3. ✅ 每个方案的资料加起来都几十 K，5 个方案塞一起必爆

**三个条件全满足，这个 demo 真的值得用多 Agent。**

---

## 一句话总结

多 Agent 不是"更高级的单 Agent"，而是对一类特殊场景的针对性设计。判断标准：**可并行 + 多视角 + 上下文需隔离**三个条件同时满足——只满足一个的，老老实实写好 prompt；两个的，加个 SubAgent；三个的，才需要常驻多 Agent 团队。

---

## 下一篇预告

这一章我们用单 Agent 做了 baseline，看到了它在四个地方系统性翻车。[下一篇](../02-minimum-skeleton/multi-agent-02-minimum-skeleton.md)就开始拆多 Agent——但不是把所有问题一次性都解决，而是**先做最克制的第一刀**：

> 1 个 Planner（拆解问题）+ N 个 Searcher（并行搜）+ 1 个 Writer（整合输出）

这个最小骨架先把"context 爆炸"和"串行慢"两个最硬的问题解掉，留下"视角单一"和"任务边界"给后面的章节。

第一刀怎么切？是按"职责"切（搜索者、阅读者、写作者），还是按"上下文边界"切（每个 worker 占独立的 context）？两种切法看起来差不多，结果差很远。第二章会摆出来对比讲清楚。

---

*「从零开始做 Multi-Agent 系统」系列建立在 [从零开始理解 Agent](../../agent/README.md) 之上，特别是第 04 章 SubAgent 和第 05 章多智能体协作。建议先读完 Agent 系列前 5 章再来。*
