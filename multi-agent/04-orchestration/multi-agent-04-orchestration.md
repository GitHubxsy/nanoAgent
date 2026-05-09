# 从零开始做 Multi-Agent 系统（四）：编排模式之争——Workflow / Supervisor / Swarm

> **「从零开始做 Multi-Agent 系统」系列** —— 第四篇。前三章搭起骨架并解决了通信问题，但骨架的"形状"——谁调度谁、谁决定何时停——还有三种不同的设计选择。这一章用三种模式各重写一遍 demo，跑完对比。
>
> - [第一篇：什么时候单 Agent 不够](../01-when-single-agent-fails/multi-agent-01-when-single-agent-fails.md)
> - [第二篇：最小多 Agent 骨架](../02-minimum-skeleton/multi-agent-02-minimum-skeleton.md)
> - [第三篇：Agent 之间怎么传话](../03-communication/multi-agent-03-communication.md)
> - **第四篇：编排模式之争**（本文）
> - [第五篇：状态、记忆与上下文](../05-state-memory/multi-agent-05-state-memory.md)
> - [第六篇：错误传播、重试与可观测性](../06-failure-trace/multi-agent-06-failure-trace.md)
> - [第七篇：边界与反模式](../07-boundaries/multi-agent-07-boundaries.md)

---

## 一、先说结论

| 模式 | 流程在哪 | 决策在何时 | 一句话评价 |
|------|---------|-----------|-----------|
| Workflow | 代码里 | 调用前 | 最可控、最便宜、最稳 |
| Supervisor | prompt 里 | 运行时 | 灵活但有"调度税" |
| Swarm | 每个 Agent 心里 | 处处发生 | 演示惊艳，生产灾难 |

一句话总结：**90% 的多 Agent 任务，最优解是 Workflow + 局部 Supervisor**——主干用 Workflow 保可控，局部用 Supervisor 保灵活。Swarm 是给少数特定场景准备的，不是默认选项。

---

## 二、三种模式的核心机制

### 2.1 Workflow（流水线）

**流程是事先编好的 DAG**，每个节点是一个 Agent，节点之间靠固定的边连接：

```python
def workflow_run(question):
    topics = planner(question)                          # 节点 1
    summaries = parallel_map(searcher, topics)           # 节点 2（并行扇出）
    report = writer(question, summaries)                 # 节点 3
    return report
```

- ✅ 流程透明，画在白板上能看清
- ✅ token 消耗最少（没有 Supervisor 的"调度税"）
- ❌ 调研中途想"再补一个方向"做不到
- ❌ 改流程要改代码

### 2.2 Supervisor（主导型）

**一个 Agent 持续主导整个流程**，其他 Agent 被它叫起来干活：

```python
def supervisor_run(question, max_rounds=12):
    summaries = {}
    for round_idx in range(max_rounds):
        decision = llm_decide(question, summaries)     # 每轮 LLM 决策
        if decision == "search:topic":
            summaries[topic] = searcher(topic)
        elif decision == "deepen:topic":
            summaries[topic] = searcher(topic, deeper=True)
        elif decision == "stop":
            break
    return writer(question, summaries)
```

- ✅ 决策集中，看到中间结果能调整方向
- ❌ Supervisor 自己的 context 持续涨
- ❌ Supervisor 是单点——出错整个系统废了

### 2.3 Swarm（去中心化）

**没有中心调度，Agent 之间自主路由**——每个 Agent 完成后自己决定"下一步交给谁"：

```python
def swarm_step(current_agent, payload):
    result = current_agent.run(payload)
    next_action = current_agent.decide_next(result)    # Agent 自主路由
    if next_action == "write":
        return writer(result)
    elif next_action.startswith("search:"):
        return swarm_step(searcher, next_action.split(":")[1])
    elif next_action.startswith("critique:"):
        return swarm_step(critic, result)
```

- ✅ 灵活，根据当下情况自由路由
- ❌ 路由本身就要花 LLM 调用
- ❌ 调试地狱——执行轨迹完全动态，难复现
- ❌ **容易死循环**——A 交给 B，B 觉得不对再交回 A

---

## 三、用三种模式各跑一遍 demo

配套代码在 [multi-agent-04-orchestration.py](./multi-agent-04-orchestration.py)，三种模式都在同一个文件里。

### 3.1 跑起来

```bash
# 跑某一种模式
OPENAI_API_KEY=... python multi-agent-04-orchestration.py workflow
OPENAI_API_KEY=... python multi-agent-04-orchestration.py supervisor
OPENAI_API_KEY=... python multi-agent-04-orchestration.py swarm
OPENAI_API_KEY=... python multi-agent-04-orchestration.py hybrid
```

### 3.2 运行对比

| 指标 | Workflow | Supervisor | Swarm |
|------|----------|-----------|-------|
| 总耗时 | ~83s | ~436s | ~48s |
| Supervisor 决策轮数 | 0 | 7 轮 | — |
| Swarm 自主路由次数 | 0 | 0 | 2 步即 write |
| 报告完整度 | 5/5 ✅ | 5/5 ✅ | 不确定 |
| 可控性 | ✓✓✓ | ✓✓ | ✗ |

几条观察：

1. **Workflow 最稳**——Planner 拆完、Searcher 并行跑完、Writer 整合，流程透明
2. **Supervisor 更深入但更慢**——每轮决策都是一次 LLM 调用，7 轮 `search` / `deepen` 花了 436 秒
3. **Swarm 不可预测**——有时两步就跳到 write，有时循环；不同模型表现差异巨大

---

## 四、最佳选择：Workflow + 局部 Supervisor

我们给 demo 选定的方案是 **外层 Workflow + 局部 Supervisor**：

```python
def hybrid_run(question):
    topics = planner(question)                              # Workflow：固定阶段

    summaries = parallel_map(supervised_search, topics)      # 每个 topic 内部小 Supervisor

    report = writer(question, summaries)                     # Workflow：固定阶段
    return report


def supervised_search(topic, max_rounds=4):
    """每个 topic 内部一个小 Supervisor，最多 4 轮。"""
    accumulated = []
    for r in range(max_rounds):
        partial = search_loop(topic, round=r)
        accumulated.append(partial)
        check = llm_check(f"主题「{topic}」当前摘要够全面了吗？")
        if check == "yes":
            break
    return "\n".join(accumulated)
```

设计要点：

| 层级 | 模式 | 作用 |
|------|------|------|
| 顶层 | Workflow | 决定大阶段：plan → search → write |
| 每个 topic 内部 | 小 Supervisor | 决定这个 topic 要不要再深入查 |
| Supervisor 上限 | `max_rounds=4` | 防止跑飞 |

这种混合方案在生产环境里非常常见：
- Workflow 提供主干的可控性
- Supervisor 提供局部的灵活性
- `max_rounds` 把不可控压在小范围里

---

## 五、什么场景该用 Swarm

为了公允，说一下 Swarm 真正适合的场景：

| 场景 | 为什么适合 Swarm |
|------|-----------------|
| 客服路由 | 按问题类型动态路由到不同领域专家，"自主路由"是核心价值 |
| 几十个 Agent | 每个负责一个垂直领域，Workflow 的固定 DAG 编不过来 |
| 高度动态任务 | 每次请求的执行路径都不同，没有可预设的流程 |

调研、代码生成、数据分析这类**有明显阶段性**的任务，**几乎都不该用 Swarm**。

---

## 一句话总结

三种编排模式不是"高级 vs 低级"的关系，而是**适用场景不同**。Workflow 最稳最便宜，Supervisor 能根据中间结果调整但有调度税，Swarm 理论灵活但实际不可控。生产环境里的最优解通常是**外层 Workflow + 局部 Supervisor + max_rounds 兜底**。

---

## 下一篇预告

三四章的 demo 已经能稳定跑出完整报告。但跑几次会发现诡异的现象：

- 5 个 Searcher 都搜了 PagedAttention 的论文（因为它无处不在）
- FlashAttention worker 写"FA 比 PA 快 2.3x"，PagedAttention worker 写"PA 比 FA 快 1.8x"——同一份报告里两个对立结论
- Writer 把矛盾的两段都写进去了，没人察觉

这些都是**状态与共享**的问题。[下一篇](../05-state-memory/multi-agent-05-state-memory.md)引入 shared scratchpad——所有 Agent 可读、Planner 可写——解决去重和冲突识别。但也会引入"过度共享"的新风险。

---

*配套代码 [multi-agent-04-orchestration.py](./multi-agent-04-orchestration.py) 包含四种模式（workflow / supervisor / swarm / hybrid），通过命令行参数切换。*
