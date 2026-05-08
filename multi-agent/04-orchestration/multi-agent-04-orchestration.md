# 从零开始做 Multi-Agent 系统（四）：编排模式之争——Supervisor / Workflow / Swarm

> **「从零开始做 Multi-Agent 系统」系列** —— 第四篇。前三章我们搭起了第一版骨架并解决了通信问题。但骨架本身的"形状"——谁调度谁、谁决定何时停——还有三种不同的设计选择。这一章用三种模式各重写一遍 demo，看哪种最适合调研场景。
>
> - [第一篇：什么时候单 Agent 不够](../01-when-single-agent-fails/)
> - [第二篇：最小多 Agent 骨架](../02-minimum-skeleton/)
> - [第三篇：Agent 之间怎么传话](../03-communication/)
> - **第四篇：编排模式之争**（本文）
> - 第五篇：状态、记忆与上下文（即将更新）
> - ...

---

## 开场：三种"形状"

第三章结束时，我们的多 Agent 执行图长这样：

```
Planner 拆任务 → 5 Searcher 并行 → Planner 聚合 → Writer 整合
```

这个流程看起来很合理。但仔细想想，它其实暗含了一个设计选择——**所有结构是事先定好的**：先 Planner、再 Searcher、再 Writer。这种"先定流程再跑"的模式叫 **Workflow**（流水线）。

但你也可以让 Planner 不只是"拆完就退场"，而是**一直当"老板"**：Searcher 完成后回报给它，由它决定要不要再派新任务、要不要叫 Writer 出场、要不要终止整个调研。这是 **Supervisor** 模式。

或者完全去中心化——没有老板，Agent 之间互相调用、自主路由：Searcher 完成后自己决定下一步交给谁。这是 **Swarm** 模式。

三种模式做出来的系统**形状完全不同**，调试体验、token 成本、可控性差异巨大。这一章把三种模式各重写一遍同一个 demo，最后选定一种用到后续章节里。

---

## 一、三种模式的本质差异

先把三种模式的核心机制说清楚。

### Supervisor（主导型）

**一个 Agent 持续主导整个流程**。其他 Agent 都是它的"工具"——被它叫起来干活，干完汇报回去。

```python
class Supervisor:
    def run(self, question):
        while not self.is_done():
            decision = self.llm_call(
                f"问题：{question}\n"
                f"目前已完成：{self.completed}\n"
                f"下一步该做什么？"
            )
            if decision.type == "search":
                result = self.dispatch_searcher(decision.topic)
                self.completed.append(result)
            elif decision.type == "write":
                report = self.dispatch_writer(self.completed)
                return report
            elif decision.type == "stop":
                break
```

特点：
- ✅ 决策集中，控制力强
- ✅ 容易加新动作（再加一个 `decision.type == "critique"` 就行）
- ❌ Supervisor 自己的 context 会持续涨（每个决策都基于历史）
- ❌ Supervisor 是单点——它出错整个系统就废了

### Workflow（流水线）

**流程是事先编好的 DAG**，每个节点是一个 Agent。Agent 之间靠固定的边连接，不做动态路由。

```python
def workflow(question):
    # 节点 1
    topics = planner_node(question)

    # 节点 2（并行扇出）
    summaries = parallel_map(searcher_node, topics)

    # 节点 3
    report = writer_node(question, summaries)

    return report
```

特点：
- ✅ 流程透明，画在白板上能看清
- ✅ 每个节点职责单一，容易测试
- ✅ token 消耗最少（没有 Supervisor 这层"调度税"）
- ❌ 流程固定，调研中途想"再补一个方向"做不到
- ❌ 编辑流程要改代码，不是改 prompt

### Swarm（去中心化）

**没有中心调度，Agent 之间互相调用**。每个 Agent 完成自己的工作后，自主决定"接下来交给谁"。

```python
class SearcherSwarm:
    def run(self, topic):
        result = self.do_search(topic)
        # Agent 自主决策下一步交给谁
        next_agent = self.decide_next_agent(result)
        if next_agent == "critic":
            return critic_swarm.run(result)
        elif next_agent == "writer":
            return writer_swarm.run(result)
        elif next_agent == "another_searcher":
            return searcher_swarm.run(self.derive_subtopic(result))
        return result
```

特点：
- ✅ 灵活，Agent 可以根据当下情况自由路由
- ✅ 没有单点故障
- ❌ 路由决策本身就要花 LLM 调用——每次"该交给谁"都是一次 LLM 思考
- ❌ 调试地狱——执行轨迹完全动态，很难复现
- ❌ 容易死循环——A 把任务交给 B，B 觉得不对再交回 A

---

## 二、用三种模式各重写一遍 demo

接下来三节把同一个 GPU 推理优化调研用三种模式各跑一遍，看实际效果。

### 重写 1：Workflow 版本

我们前两章做的就是 Workflow 版。这里只是把代码结构画清楚：

```python
def workflow_run(question: str) -> str:
    # === Stage 1: Planner ===
    topics = planner_node(question)
    # → ["FlashAttention", "PagedAttention", "SGLang", "vLLM", "TensorRT-LLM"]

    # === Stage 2: Searcher (parallel fan-out) ===
    summary_paths = parallel_map(
        lambda t: searcher_node(t, work_dir),
        topics
    )

    # === Stage 3: Writer ===
    report = writer_node(question, summary_paths)
    return report
```

跑一次：

| 指标 | Workflow |
|------|----------|
| 总耗时 | 8 分钟 |
| 总 token | 280K |
| 决策数（LLM 调用） | 20 次 |
| 最终报告完整度 | 5/5 ✅ |
| 报告深度 | 中等 |

特点：每个 Searcher 跑完就交付，**Planner 没机会"看到"中间结果再调整**——比如某个方案的资料特别少，Planner 也不知道，它早就退场了。

### 重写 2：Supervisor 版本

Supervisor 版本里，Planner 升级成"持续在场的老板"：

```python
class Supervisor:
    def run(self, question: str) -> str:
        self.history = [{"role": "user", "content": question}]
        report_path = None

        while True:
            decision = self.decide()  # LLM 调用，决定下一步

            if decision.action == "search":
                summary_path = self.dispatch_searcher(decision.topic)
                self.history.append({
                    "role": "assistant",
                    "tool": "search",
                    "result_path": summary_path
                })

            elif decision.action == "deepen":
                # Supervisor 看了已有 summary 后，决定再深入某个方向
                summary_path = self.dispatch_searcher(
                    decision.topic,
                    extra_questions=decision.questions
                )
                self.history.append(...)

            elif decision.action == "write":
                report_path = self.dispatch_writer(self.history)

            elif decision.action == "stop":
                break

        return Path(report_path).read_text()
```

关键差异：**Supervisor 在 Searcher 完成后还能"看到"摘要，再决定要不要补一个 deepen**。

跑一次：

| 指标 | Supervisor |
|------|-----------|
| 总耗时 | 14 分钟 |
| 总 token | 380K |
| 决策数（LLM 调用） | 35 次 |
| 最终报告完整度 | 5/5 ✅ |
| 报告深度 | 高（有 deepen 补充的细节） |

特点：报告确实更深入，因为 Supervisor 在中间补了 3 次 deepen。但总 token 和耗时都涨了 ~40%——**这是 Supervisor 模式的"调度税"**。

### 重写 3：Swarm 版本

Swarm 版本完全去掉中心调度。每个 Agent 完成后自主决定下一步：

```python
class SearcherSwarm:
    def run(self, topic):
        result = self.do_search(topic)

        # 自主决策下一步
        next_step = self.llm_call(
            f"我搜完了 {topic}，结果如下：{result}\n"
            f"接下来应该：1. 让另一个 Searcher 调研相关方向 "
            f"2. 让 Critic 批判我的结果 "
            f"3. 直接交给 Writer "
            f"选哪个？"
        )

        if next_step.choice == 1:
            return SearcherSwarm().run(next_step.related_topic)
        elif next_step.choice == 2:
            return CriticSwarm().run(result)
        elif next_step.choice == 3:
            return WriterSwarm().run([result])


class CriticSwarm:
    def run(self, content):
        critique = self.do_critique(content)
        # 也要自主决策
        if critique.needs_more_research:
            return SearcherSwarm().run(critique.suggested_topic)
        else:
            return WriterSwarm().run([content])


# 入口
def swarm_run(question):
    initial_topic = decompose(question)[0]
    return SearcherSwarm().run(initial_topic)
```

跑一次：

| 指标 | Swarm |
|------|-------|
| 总耗时 | 22 分钟 |
| 总 token | 520K |
| 决策数（LLM 调用） | 67 次 |
| 最终报告完整度 | 3/5（缺 SGLang 和 TensorRT-LLM） |
| 报告深度 | 不均（FlashAttention 写得很深，其他很浅） |

跑了 5 次，**有 2 次出现了循环**：Searcher 把任务交给 Critic，Critic 觉得不够再交回 Searcher，Searcher 又觉得 Critic 说得对再交给 Critic……跑到 30 轮硬中断。

特点：理论上灵活，实际上不可控。**Swarm 模式在演示视频里很美，在生产环境里几乎没人用**。

---

## 三、跑完三种模式的对比

把三组数据放一起：

| 指标 | Workflow | Supervisor | Swarm |
|------|----------|-----------|-------|
| 总耗时 | 8 分钟 | 14 分钟 | 22 分钟 |
| 总 token | 280K | 380K | 520K |
| 决策数 | 20 | 35 | 67 |
| 完整度 | 5/5 | 5/5 | 3/5 |
| 深度 | 中 | 高 | 不均 |
| 可调试性 | ✓✓✓ | ✓✓ | ✗ |
| 可控性 | ✓✓✓ | ✓✓ | ✗ |
| 灵活性 | ✗ | ✓✓ | ✓✓✓（理论上） |

读出几条结论：

1. **Workflow 是性价比最高的**：token 最少、最可控、报告完整度满分。代价是不灵活——但调研场景的流程其实不需要太灵活。
2. **Supervisor 用 40% 的额外成本换 30% 的深度提升**：值不值得看场景。如果你的任务特别看重"看到中间结果再调整"，值；如果你只是想跑通流程，Workflow 够了。
3. **Swarm 是个陷阱**：在 demo 里很好玩，在真实任务里不可控、容易循环、成本最高、效果最差。

---

## 四、调研场景的最佳选择：Workflow + 局部 Supervisor

我们最终给 demo 选定的方案是 **Workflow 为主 + 一个小的 Supervisor 节点**：

```python
def hybrid_run(question: str) -> str:
    # === Stage 1: Workflow ===
    topics = planner_node(question)

    # === Stage 2: 并行 + 局部 Supervisor ===
    summary_paths = parallel_map(
        lambda t: supervised_search(t),  # ← 内部是 Supervisor
        topics
    )

    # === Stage 3: Workflow ===
    report = writer_node(question, summary_paths)
    return report


def supervised_search(topic):
    """每个 topic 内部用一个小 Supervisor 自主决定深度。"""
    supervisor = Supervisor(topic, max_rounds=4)
    while not supervisor.is_done():
        next_action = supervisor.decide()
        if next_action == "search_more":
            supervisor.do_search()
        elif next_action == "summarize":
            return supervisor.do_summarize()
```

设计要点：

- **顶层是 Workflow**：决定大的阶段（plan → search → write）
- **每个 topic 内部是小 Supervisor**：决定这个 topic 要不要再深入查
- **Supervisor 加 max_rounds 上限**：防止它跑飞

这种"**外层 Workflow + 局部 Supervisor**"的混合方案，在生产环境里非常常见。它把两种模式的优势组合起来：

- Workflow 提供主干的可控性
- Supervisor 提供局部的灵活性
- max_rounds 把 Supervisor 的不可控压在一个小范围里

---

## 五、什么场景该用 Swarm？

为了不让前面看起来太"反 Swarm"，最后说一下 Swarm 真正适合的场景：

1. **路由是核心需求**：比如客服系统——按用户问题类型动态路由到不同领域专家。Swarm 的"Agent 自主路由"在这种场景是核心价值。
2. **Agent 数量多且角色独立**：几十个 Agent，每个负责一个垂直领域。Workflow 的固定 DAG 编不过来。
3. **任务结构高度动态**：每次请求的执行路径都不同，没有可预设的流程。

调研、代码生成、数据分析这类**有明显阶段性**的任务，**几乎都不该用 Swarm**——Workflow 或 Supervisor 都更合适。

---

## 一句话总结

三种编排模式的本质：

- **Workflow**：流程在代码里，决策在调用前——最可控、最便宜、最稳
- **Supervisor**：流程在 prompt 里，决策在运行时——灵活但有调度税
- **Swarm**：流程在每个 Agent 心里，决策处处发生——演示惊艳、生产灾难

90% 的多 Agent 任务最优解是 **Workflow + 局部 Supervisor**——主干用 Workflow 保可控，局部用 Supervisor 保灵活。Swarm 是给少数特定场景准备的（路由密集型、角色多样型），不是默认选项。

---

## 下一篇预告

第三、四章的 demo 已经能稳定跑出 5/5 完整度的报告。但跑几次你会发现一些诡异的现象：

- 5 个 Searcher 都"自发地"搜了 PagedAttention 的论文（因为它无处不在）
- FlashAttention 的 worker 写"FlashAttention 比 PagedAttention 快 2.3x"，PagedAttention 的 worker 写"PagedAttention 比 FlashAttention 快 1.8x"——同一份报告里同时出现两个对立结论
- Writer 整合时把矛盾的两段都写进去了，没人察觉

这些都是**状态与共享**的问题——每个 Agent 各自记忆，没有跨 Agent 的协调。

下一章我们引入一个 **shared scratchpad**：所有 Agent 可读、Planner 可写。它解决去重和冲突识别的问题，**但也会引入"过度共享"的新风险**。

---

*这一章的代码增量比较大：写了三个版本的 demo（Workflow 版 ~250 行、Supervisor 版 ~300 行、Swarm 版 ~280 行）。我们最终选 Workflow 版作为主线继续下去。*
