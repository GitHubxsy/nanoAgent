# 从零开始做 Multi-Agent 系统（二）：最小骨架——Supervisor + Workers

> **「从零开始做 Multi-Agent 系统」系列** —— 第二篇。第一篇用单 Agent baseline 跑通了一遍 GPU 推理优化调研，看到了它在四个地方系统性翻车。这一篇开始动手拆多 Agent，但**只做最克制的第一刀**。
>
> - [第一篇：什么时候单 Agent 不够](../01-when-single-agent-fails/)
> - **第二篇：最小多 Agent 骨架——Supervisor + Workers**（本文）
> - 第三篇：Agent 之间怎么传话（即将更新）
> - ...

---

## 开场：第一刀该怎么切？

第一章我们用单 Agent 跑了一遍调研，看到了四个翻车点：context 爆炸、串行慢、视角单一、任务边界乱。

现在你打开编辑器，准备拆多 Agent。第一个问题就把你卡住了：

> **第一刀该怎么切？**

打开 X 翻一圈，会看到至少三种"切法"：

1. **按职责切**：Searcher、Reader、Summarizer、Writer——每个 Agent 做一件事
2. **按角色切**：CEO Agent、Researcher Agent、Critic Agent——像组建一个小团队
3. **按上下文边界切**：哪个子任务的上下文会爆，就把它独立出去

听起来差不多对吧？但**这三种切法做出来的系统差异巨大**。第一种最直觉、最常被采用，效果反而最差。

这一章把这三种切法摆出来对比，定下一个原则：**第一刀必须按"上下文边界"切，不是按"职责性感"切**。

---

## 一、三种切法对比

### 切法 A：按职责切

最直觉的拆法。每个 Agent 负责一件具体的事：

```
Searcher  → 调用搜索引擎
Reader    → 抓取网页正文
Summarizer→ 总结一段文本
Writer    → 写报告
```

听起来很合理。问题是：

- **Searcher 搜回来的结果还是要塞回主循环，让 Reader 决定读哪些**——这意味着 Searcher 的所有结果都要跨 Agent 传递，**通信开销巨大**。
- **每个 Agent 的职责都很轻**，每次调用都要 LLM 决策"这一步该让谁干"，**调度开销 > 实际工作开销**。
- **每多一个职责就多一个 Agent**，系统复杂度线性膨胀。

按职责切的本质问题是：**职责的颗粒度和上下文的颗粒度不一致**。Searcher 一次只搜一条，但 5 条搜索结果一起才有意义；Reader 一次只读一篇，但要交叉对比好几篇才能下判断。

### 切法 B：按角色切

把 Agent 当人来设计：

```
CEO       → 决定调研什么、什么时候停
Researcher→ 收集信息
Critic    → 批判信息
Writer    → 写报告
```

这种切法在很多 demo 里很性感，但生产环境里几乎都翻车。原因是：

- **角色之间的边界模糊**——Researcher 收集信息时也在做轻度判断；Critic 批判时也要补充查证；Writer 写作时也在做整合判断。这些重叠让任务交接非常啰嗦。
- **角色的职责不能映射到 token 边界**——CEO Agent 占 5K context，Researcher 占 60K，Critic 占 20K——它们的资源需求差几个量级，但被同等对待。
- **角色拟人化会让 prompt 越写越长**——"作为一个严谨的 Researcher，你应该……"这种描述对效果几乎没贡献，全是 token 噪声。

### 切法 C：按上下文边界切

换一个视角：**哪部分子任务的上下文会爆，就把它拆出去独立成 Agent**。

GPU 推理优化调研里，"爆上下文"的部分是**搜索 + 阅读 5 个方案的资料**。这些资料每个方案就有几十 K，5 个塞一起必爆。

所以第一刀就该切在这里：

```
Planner Agent (主循环)
  → 拆任务成 5 个子调研
  → 起 5 个 Searcher worker，每个负责一个方案
  → 收集 worker 的产出（摘要，不是原文）
  → 调用 Writer 整合输出

每个 Searcher worker
  → 自己的独立 context
  → 自己搜、自己读、自己总结
  → 只把摘要交回给 Planner
```

这种切法的关键是：**worker 的 context 不会污染主循环**。Planner 永远不会看到原始论文正文，它只看 worker 交回的"FlashAttention-3 在长上下文场景的核心改进 + 关键性能数字"这种几百 token 的摘要。

5 个方案 × 几十 K 的原文 → 只有 5 × 几百 token 的摘要会进主循环。**这是多 Agent 真正赢单 Agent 的关键**。

---

## 二、第一版骨架：1 Planner + N Searchers + 1 Writer

把上面的设计落到代码层面，第一版骨架长这样：

```python
# pseudo-code，简化版

class Planner:
    """主循环。负责拆任务、起 worker、收集结果、触发 writer。"""
    def run(self, question: str) -> str:
        # 1. 拆任务
        subtopics = self.llm_call(
            f"把这个调研问题拆成几个并行子调研：{question}"
        )
        # 比如返回：["FlashAttention", "PagedAttention", "SGLang", "vLLM", "TensorRT-LLM"]

        # 2. 并行起 worker
        summaries = parallel_map(
            lambda topic: Searcher(topic).run(),
            subtopics
        )

        # 3. 调 writer
        report = Writer().run(question, summaries)
        return report


class Searcher:
    """每个 worker 一个独立的 context。"""
    def __init__(self, topic: str):
        self.topic = topic
        self.tools = [web_search, web_read]
        self.history = []  # 自己的 context，不和别人共享

    def run(self) -> str:
        # 内部跑一个标准 Agent loop：搜、读、再搜、写摘要
        # 返回一份 ~500 token 的摘要
        ...


class Writer:
    """整合所有摘要，写最终报告。"""
    def run(self, question: str, summaries: list[str]) -> str:
        return self.llm_call(
            f"基于以下子调研摘要，写一份报告回答：{question}\n\n摘要：{summaries}"
        )
```

整套代码结构大概 200 行 Python。和单 Agent 比，多了：

- 一个 `parallel_map`（用线程池或者 `asyncio.gather` 都行）
- 三个 prompt（Planner 拆任务、Searcher 自循环、Writer 整合）

就这些。**没有用任何多 Agent 框架**——CrewAI、AutoGen、LangGraph 一个都没用。这是有意的：第一版越小越好，让你看清楚每个设计选择。

---

## 三、Planner 怎么决定拆几个 worker

上面的代码里有一个细节藏得很深：**Planner 怎么知道该拆 5 个 worker 而不是 50 个？**

这是多 Agent 系统的隐藏成本——**任务拆分本身是个任务**，而且做得不好的话比单 Agent 还糟。

观察几种常见的拆分策略：

| 策略 | 怎么做 | 问题 |
|------|--------|------|
| 模型自由拆 | "把这个问题拆成几个子调研" | 模型可能拆 3 个，也可能拆 30 个；不可控 |
| 固定数量 | "拆成正好 5 个" | 不同问题需要的子调研数差异大，强行 5 个会浪费或漏掉 |
| 给上界 | "拆成最多 8 个，每个子调研要独立" | **当前最稳的策略** |
| 双轮拆分 | 先拆 3 个，做完看缺什么，再拆补充的 | 准确但慢，token 翻倍 |

经验法则：**给一个上界 + 强调"独立"约束**。比如：

```python
PLANNER_PROMPT = """
把这个调研问题拆成 3-8 个并行的子调研。要求：
- 每个子调研可以独立完成，不依赖其他子调研的结果
- 每个子调研的资料量在 50K token 以内
- 子调研之间不要有明显重叠

调研问题：{question}

返回 JSON 数组，每个元素是 {{"topic": "...", "key_questions": [...]}}
"""
```

加了"独立"和"不重叠"约束后，模型拆出来的子任务质量会显著提升。

但即使这样，**worker 之间还是会有重叠**——比如调研 vLLM 时绕不开 PagedAttention。这是第 5 章 "状态与共享" 要解决的问题。这一章先假装它不存在。

---

## 四、Worker 之间需要互通吗？

第一版骨架里，所有 worker 都是**完全独立**的——它们之间不通信、不共享状态、不知道彼此的存在。

这个设计是有意为之的。原因是：

**Worker 互通会立即让你陷入分布式系统的所有经典问题**——竞态、死锁、消息顺序、状态一致性。这些问题在单进程的 Python 里都不简单，在多 Agent 系统里更难调试（因为模型不会按你想的顺序行动）。

第一版的策略是：**用"完全独立 + 重复劳动"换"简单 + 可靠"**。

具体来说：

- ✅ Worker 之间不通信
- ✅ 即使两个 worker 搜了同样的论文，也算"重复劳动"，不去优化
- ✅ Worker 的结果统一交回 Planner，不直接交给彼此

代价是什么？**多花了一些 token**——但相比于"加上互通后调试不出问题"的代价，这个代价非常划算。

第 5 章我们会再回来处理"重复劳动"的问题，但用的是**共享只读 scratchpad** 而不是 worker 间直接通信。这是两件本质不同的事。

---

## 五、跑一次第一版，对比单 Agent

把第一版骨架跑起来，同样的 GPU 推理优化调研问题，对比第一章的单 Agent baseline：

| 指标 | 单 Agent baseline | 第一版多 Agent | 变化 |
|------|------------------|---------------|------|
| 总耗时 | 30+ 分钟 | 8 分钟 | ↓ 73% |
| 主循环 context 峰值 | ~120K tokens | ~15K tokens | ↓ 87% |
| 总 token 消耗 | ~200K | ~280K | ↑ 40% |
| 报告完整度（5 个方案覆盖） | 3/5（2 个写得很浅） | 5/5 | ✅ |
| 信息冲突识别 | 0 | 0 | 不变 |

读出几件事：

1. **"context 爆炸"和"串行慢"两个问题被解决了**——主循环 context 降了 87%，耗时降了 73%。
2. **总 token 消耗反而上升了 40%**——这是多 Agent 的"沟通税"，下一章会专门讨论。
3. **报告完整度从 3/5 提升到 5/5**——5 个方案现在都被均匀覆盖了。
4. **"视角单一"问题没解决**——第一版没加 critic，信息冲突还是识别不出来。
5. **"任务边界乱"问题部分解决**——Planner / Searcher / Writer 各做一件事，但每个 Agent 内部还是混着搜索 + 阅读 + 总结。

这个结果是**预期之中的**。第一刀只是切掉了最大的两个问题，剩下的留给后面的章节。

---

## 六、第一版的明显问题（埋后续章节的坑）

第一版能跑了，但你跑几次会发现这些问题：

### 问题 1：摘要怎么传回去？

Searcher 给 Planner 交回的是字符串摘要。但如果摘要里有"参考论文：xxx.pdf"这种引用，Writer 想原文核对就拿不到了。

**这是通信方式的问题——下一章解决**。

### 问题 2：所有 worker 跑完才能进入 Writer

第一版的执行图是 `Planner → 5 个 Searcher (并行) → Writer`。如果有 1 个 Searcher 卡住了（API 超时、内容找不到），整个 Writer 阶段都得等。

**这是编排模式的问题——第 4 章 Workflow vs Supervisor 解决**。

### 问题 3：Searcher 之间重复劳动

vLLM 和 PagedAttention 的 worker 都会去搜 PagedAttention 的论文。重复劳动浪费 token。

**这是状态共享的问题——第 5 章 shared scratchpad 解决**。

### 问题 4：没有 critic，信息冲突识别不出来

报告里仍然会同时引用对立的两篇博客。

**这是视角多样性的问题——第 6 章 critic Agent 解决**。

### 问题 5：一个 Searcher 跑挂了，整个调研废了

`parallel_map` 里如果 1 个抛异常，剩下 4 个的结果也丢了。

**这是错误处理的问题——第 6 章 retry + critic 解决**。

---

## 一句话总结

多 Agent 的第一刀，**按"上下文边界"切，不是按"职责性感"切**。

具体到调研场景：1 个 Planner 拆任务、N 个 Searcher 并行调研、1 个 Writer 整合。每个 Searcher 在自己独立的 context 里跑完整循环，只把摘要交回主线——主线永远不接触原始资料。

这个最小骨架解掉了"context 爆炸"和"串行慢"两个最硬的问题，但留下了通信、编排、共享状态、错误处理、视角多样性五个新问题。这是后续 5 章的工作。

---

## 下一篇预告

第一版骨架里，Searcher 给 Planner 交回的是字符串。这看起来简单，但**字符串不够用**——摘要里的引用拿不到原文、Worker 跑挂了状态丢失、长摘要又会让 Planner context 涨。

下一章讨论一个看起来很基础但其实很关键的问题：**Agent 之间到底用什么传话？**

主流有三种方式：消息（直接传字符串）、共享状态（黑板模式）、文件（写到磁盘下游读）。三种方式的 token 成本、状态一致性、调试难度差异巨大。我们会给 demo 选定一个混合方案：**Searcher 写文件，Writer 读文件，Planner 用消息发任务**——并解释为什么不全用消息。

---

*这一章的代码（约 200 行 Python）会作为后续章节的起点。我们的 nano-multi-agent 从这里开始一步步长大。*
