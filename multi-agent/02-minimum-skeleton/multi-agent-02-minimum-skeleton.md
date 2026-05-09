# 从零开始做 Multi-Agent 系统（二）：最小骨架——Planner + Workers + Writer

> **「从零开始做 Multi-Agent 系统」系列** —— 第二篇。上一篇用单 Agent 跑通调研 demo，看到了四个系统性翻车点。这一篇开始动手拆多 Agent——但只做最克制的第一刀。
>
> - [第一篇：什么时候单 Agent 不够](../01-when-single-agent-fails/multi-agent-01-when-single-agent-fails.md)
> - **第二篇：最小多 Agent 骨架**（本文）
> - [第三篇：Agent 之间怎么传话](../03-communication/multi-agent-03-communication.md)
> - [第四篇：编排模式之争](../04-orchestration/multi-agent-04-orchestration.md)
> - [第五篇：状态、记忆与上下文](../05-state-memory/multi-agent-05-state-memory.md)
> - [第六篇：错误传播、重试与可观测性](../06-failure-trace/multi-agent-06-failure-trace.md)
> - [第七篇：边界与反模式](../07-boundaries/multi-agent-07-boundaries.md)

---

## 一、先说结论

| 拆法 | 怎么拆 | 结果 |
|------|--------|------|
| 按职责切 | Searcher、Reader、Summarizer、Writer 各一个 | 调度开销 > 实际工作，通信爆炸 |
| 按角色切 | CEO、Researcher、Critic、Writer | 角色边界模糊，prompt 噪声大 |
| **按上下文边界切** | **哪部分会爆 context，就独立出去** | **真正解决问题** |

一句话总结：**第一刀必须按"上下文边界"切，不是按"职责性感"切**。具体到调研场景：1 个 Planner 拆任务、N 个 Searcher 并行调研（各自独立 context）、1 个 Writer 整合摘要。

---

## 二、三种切法，为什么只有一种靠谱

### 2.1 切法 A：按职责切

最直觉的拆法——每个 Agent 负责一件具体的事：

```
Searcher   → 调用搜索引擎
Reader     → 抓取网页正文
Summarizer → 总结一段文本
Writer     → 写报告
```

问题是：

- Searcher 搜回来的结果还是要塞回主循环让 Reader 决定读哪些——**通信开销巨大**
- 每个 Agent 职责很轻，每次都要 LLM 决策"该让谁干"——**调度开销 > 实际工作**
- 每多一个职责就多一个 Agent——系统复杂度线性膨胀

本质问题：**职责的颗粒度和上下文的颗粒度不一致**。Searcher 一次只搜一条，但 5 条搜索结果一起才有意义；Reader 一次只读一篇，但要交叉对比好几篇才能下判断。

### 2.2 切法 B：按角色切

把 Agent 当人来设计：

```
CEO        → 决定调研什么、什么时候停
Researcher → 收集信息
Critic     → 批判信息
Writer     → 写报告
```

在 demo 里很性感，生产环境几乎都翻车：

- **角色边界模糊**——Researcher 收集信息时也在做判断，Critic 批判时也要补充查证，Writer 写作时也在整合。交接非常啰嗦
- **角色不能映射到 token 边界**——CEO 占 5K context，Researcher 占 60K，资源差几个量级但被同等对待
- **角色拟人化让 prompt 越写越长**——"作为一个严谨的 Researcher，你应该……"这种描述对效果几乎没贡献

### 2.3 切法 C：按上下文边界切

换一个视角：**哪部分子任务的上下文会爆，就把它拆出去**。

GPU 推理优化调研里，"爆上下文"的部分是搜索 + 阅读 5 个方案的资料。每个方案几十 K，5 个塞一起必爆。所以第一刀切在这里：

```
Planner（主循环）
  → 拆任务成 N 个子调研
  → 起 N 个 Searcher worker（并行，各自独立 context）
  → 收集 worker 的产出（摘要，不是原文）
  → 调用 Writer 整合输出

每个 Searcher worker
  → 自己的 context，不和别人共享
  → 自己搜、自己读、自己总结
  → 只把摘要交回给 Planner
```

> **关键洞察**：worker 的 context 不会污染主循环。Planner 永远不看原始论文正文，只看 worker 交回的几百 token 摘要。5 个方案 × 几十 K 的原文 → 只有 5 × 几百 token 进主循环。**这才是多 Agent 真正赢单 Agent 的地方**。

---

## 三、代码实现：约 160 行 Python

配套代码在 [multi-agent-02-minimum-skeleton.py](./multi-agent-02-minimum-skeleton.py)。没有用任何框架——CrewAI、AutoGen、LangGraph 一个都没用。第一版越小越好，让你看清每个设计选择。

### 3.1 Planner：拆任务

```python
def planner(question: str) -> list[str]:
    out = llm_chat([
        {"role": "system", "content": "把调研问题拆成 3-8 个独立、不重叠的子调研主题。"
                                       "返回 JSON 数组，元素是字符串。"},
        {"role": "user", "content": question},
    ])
    text = out["message"].content or ""
    start, end = text.find("["), text.rfind("]")
    return json.loads(text[start:end+1]) if start >= 0 < end else []
```

Planner 做的唯一一件事：把一个大问题拆成 N 个独立的子问题。"独立"是关键约束——后面并行靠它。

### 3.2 Searcher：每个 worker 独立循环

```python
def searcher(topic: str, max_iters: int = 8) -> str:
    messages = [
        {"role": "system", "content": f"你是专项调研员，只调研「{topic}」。"
                                       f"通过 web_search + web_read 收集资料，"
                                       f"最后用一段话（200-400 字）总结。"},
        {"role": "user", "content": f"调研 {topic}"},
    ]
    for _ in range(max_iters):
        msg = llm_chat(messages, tools=SEARCH_TOOLS)["message"]
        messages.append(msg)
        if not msg.tool_calls:
            return msg.content or "(空摘要)"
        for tc in msg.tool_calls:
            result = SEARCH_FNS[tc.function.name](**json.loads(tc.function.arguments))
            messages.append({"role": "tool", "tool_call_id": tc.id, "content": result[:6000]})
    return "(超过迭代上限)"
```

每个 Searcher 就是 [Agent 系列第一篇](../../agent/01-essence/agent-essence.md) 里的标准 Agent 循环——`LLM → 检查 tool_calls → 执行工具 → 回填 messages → 继续`。唯一的区别是它有自己独立的 `messages`，不和任何人共享。

### 3.3 并行执行 + Writer 整合

```python
def run_workflow(question: str) -> str:
    topics = planner(question)                      # Step 1: 拆任务

    summaries = {}
    with ThreadPoolExecutor(max_workers=len(topics)) as pool:
        futures = {pool.submit(searcher, t): t for t in topics}
        for fut in as_completed(futures):
            summaries[futures[fut]] = fut.result()  # Step 2: 并行搜

    report = writer(question, summaries)            # Step 3: 整合写报告
    return report
```

整个编排逻辑就这 8 行。`ThreadPoolExecutor` 负责并行，`as_completed` 逐个收集结果，最后交给 Writer 整合。

### 3.4 跑起来

```bash
OPENAI_API_KEY=... python multi-agent-02-minimum-skeleton.py
```

> 同样内置 mock 工具，不需要真实搜索 API。

---

## 四、Planner 怎么决定拆几个 worker

Planner 的拆分质量直接决定整个系统的效果。观察几种常见策略：

| 策略 | 做法 | 问题 |
|------|------|------|
| 模型自由拆 | "把这个问题拆成几个子调研" | 可能拆 3 个也可能拆 30 个，不可控 |
| 固定数量 | "拆成正好 5 个" | 不同问题需要的数量差异大 |
| **给上界** | **"拆成 3-8 个，每个要独立"** | **当前最稳** |
| 双轮拆分 | 先拆 3 个，做完看缺什么再补 | 准确但慢，token 翻倍 |

经验法则：**给一个上界 + 强调"独立"约束**。加了"独立"和"不重叠"后，模型拆出来的子任务质量显著提升。

但即使这样，worker 之间还是会有重叠——比如调研 vLLM 时绕不开 PagedAttention。这是第 5 章"状态与共享"要解决的问题，这一章先假装它不存在。

---

## 五、Worker 之间需要互通吗？

第一版里，所有 worker **完全独立**——不通信、不共享状态、不知道彼此存在。

这是有意为之的。Worker 互通会立即让你陷入分布式系统的经典问题——竞态、死锁、消息顺序、状态一致性。在多 Agent 系统里更难调试，因为模型不会按你想的顺序行动。

第一版的策略：**用"完全独立 + 重复劳动"换"简单 + 可靠"**。

- ✅ Worker 之间不通信
- ✅ 两个 worker 搜了同样的论文？算"重复劳动"，不优化
- ✅ Worker 的结果统一交回 Planner，不直接交给彼此

代价是多花一些 token——但相比"加上互通后调试不出问题"的代价，非常划算。

第 5 章会回来处理重复劳动，但用的是**共享只读 scratchpad**，不是 worker 间直接通信。这是两件本质不同的事。

---

## 六、跑一次，对比单 Agent

同样的 GPU 推理优化调研问题，对比第一章的单 Agent baseline：

| 指标 | 单 Agent | 第一版多 Agent | 变化 |
|------|---------|--------------|------|
| 总耗时 | 86s（串行） | 30s（并行） | ↓ 65% |
| 主循环 context 峰值 | ~80K tokens | ~15K tokens | ↓ 81% |
| 报告完整度（5 方案覆盖） | 3/5 | 5/5 | ✅ |
| 信息冲突识别 | 0 | 0 | 不变 |

读出几件事：

1. **"context 爆炸"和"串行慢"被解决了**——主循环 context 降了 81%，耗时降了 65%
2. **报告完整度从 3/5 到 5/5**——5 个方案均匀覆盖了
3. **"视角单一"没解决**——没加 critic，信息冲突还是识别不出来
4. **"任务边界乱"部分解决**——Planner / Searcher / Writer 各管一件事，但 Searcher 内部还是混着搜索 + 阅读 + 总结

这个结果符合预期。第一刀只切掉最大的两个问题，剩下的留给后面的章节。

---

## 七、第一版的明显问题

跑几次会发现这些问题——它们分别对应后续章节：

| 问题 | 表现 | 哪章解决 |
|------|------|---------|
| 摘要怎么传回去 | 字符串摘要里的引用拿不到原文，Writer 无法核对 | [第三篇：通信](../03-communication/multi-agent-03-communication.md) |
| 所有 worker 跑完才能写报告 | 1 个卡住，Writer 就得等 | [第四篇：编排](../04-orchestration/multi-agent-04-orchestration.md) |
| worker 重复劳动 | vLLM 和 PagedAttention 的 worker 都去搜了同一篇论文 | [第五篇：状态共享](../05-state-memory/multi-agent-05-state-memory.md) |
| 没有 critic | 报告同时引用对立的博客，没察觉冲突 | [第六篇：critic + 重试](../06-failure-trace/multi-agent-06-failure-trace.md) |
| 一个 worker 挂了全废 | `parallel_map` 里 1 个抛异常，4 个的结果也丢了 | [第六篇：错误隔离](../06-failure-trace/multi-agent-06-failure-trace.md) |

---

## 一句话总结

多 Agent 的第一刀，**按"上下文边界"切**——哪部分会爆 context，就把它独立出去。1 个 Planner 拆任务、N 个 Searcher 并行调研、1 个 Writer 整合。每个 Searcher 在独立 context 里跑完整循环，只把摘要交回主线。这解掉了"context 爆炸"和"串行慢"两个最硬的问题，但留下了通信、编排、共享状态、错误处理、视角多样性五个新问题——后面五章逐个解决。

---

## 下一篇预告

第一版骨架里，Searcher 给 Planner 交回的是字符串。这看起来简单，但**字符串不够用**——摘要里的引用拿不到原文、Worker 跑挂了状态丢失、长摘要又让 Planner context 涨。

[下一篇](../03-communication/multi-agent-03-communication.md)讨论一个看起来基础但其实关键的问题：**Agent 之间到底用什么传话？** 三种方式——消息、共享状态、文件——的 token 成本和调试难度差异巨大。

---

*配套代码 [multi-agent-02-minimum-skeleton.py](./multi-agent-02-minimum-skeleton.py) 约 160 行，是后续章节的起点。*
