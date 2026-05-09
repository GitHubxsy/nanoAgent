# 从零开始做 Multi-Agent 系统（七）：边界与反模式——什么时候该退回单 Agent

> **「从零开始做 Multi-Agent 系统」系列** —— 第七篇（终章）。前六章一步步把单 Agent baseline 做成了产品级雏形的多 Agent 系统。这一章回头算账——哪些步真的赢了、哪些是"沟通税"，并给出反模式清单和折中方案。
>
> - [第一篇：什么时候单 Agent 不够](../01-when-single-agent-fails/multi-agent-01-when-single-agent-fails.md)
> - [第二篇：最小多 Agent 骨架](../02-minimum-skeleton/multi-agent-02-minimum-skeleton.md)
> - [第三篇：Agent 之间怎么传话](../03-communication/multi-agent-03-communication.md)
> - [第四篇：编排模式之争](../04-orchestration/multi-agent-04-orchestration.md)
> - [第五篇：状态、记忆与上下文](../05-state-memory/multi-agent-05-state-memory.md)
> - [第六篇：错误传播、重试与可观测性](../06-failure-trace/multi-agent-06-failure-trace.md)
> - **第七篇：边界与反模式**（本文）

---

## 一、先说结论

| 条件满足数 | 推荐方案 | 典型场景 |
|-----------|---------|---------|
| 0-1 个 | 单 Agent + 好 prompt | 代码生成、简单问答 |
| 2 个 | 单 Agent + SubAgent 临时调用 | 中等复杂度的调研、分析 |
| **3 个全满足** | **完整多 Agent 团队** | **大规模并行调研、跨域协作** |

三个条件：**任务可并行 + 视角需多样 + 上下文需隔离**。

一句话总结：**多 Agent 不是更高级的单 Agent，而是对一类特殊场景的针对性设计**。70% 看起来"需要多 Agent"的问题，单 Agent + SubAgent 就能解决。

---

## 二、六章之后，回头算账

回到第一章的 GPU 推理优化调研问题，把单 Agent baseline 和完整多 Agent 的数据摆出来：

| 指标 | 单 Agent baseline（第一章） | 完整多 Agent（第六章末） | 变化 |
|------|---------------------------|------------------------|------|
| 总耗时 | 30+ 分钟 | 13 分钟 | ↓ 57% |
| 主循环 context 峰值 | ~120K tokens | ~15K tokens | ↓ 87% |
| 总 token 消耗 | ~200K | ~480K | ↑ 140% |
| 成功率（5/5 完整度） | 60% | 95% | ↑ 35pp |
| 信息冲突识别 | 0 个 | 2-3 个 | ↑ |
| 代码量 | ~80 行 | ~570 行 | 7x |

读出几件事：

1. **质量上多 Agent 全面胜出**——成功率 +35pp，识别出冲突
2. **耗时降了一半**——并行的功劳
3. **token 涨了 140%**——这就是"沟通税"
4. **代码量涨了 7 倍**——多出来的 490 行里，只有约 100 行是核心逻辑，其余 390 行是工程骨架（错误处理、trace、scratchpad、retry）

> **关键洞察**：**多 Agent 系统的"工程税"远大于"逻辑税"**。一个 100 行能讲清楚的想法，做成生产级实现要 500 行——多出来的全是工程基础设施。

---

## 三、Token 去哪了

把 480K token 按用途拆开：

| 类别 | 占比 | 包含 |
|------|------|------|
| 实际工作 | 50% | Searcher 搜索 + 阅读 + 总结 |
| 质量保证 | 20% | Critic 批判 + Writer 修正 |
| 沟通税 | 11% | 消息传递 + 协调 + 通信 |
| 鲁棒性税 | 9% | 重试 + schema 校验 |
| 其他 | 10% | 调度、格式化、system prompt |

**只有一半的 token 是在做"实际调研"，另一半全是多 Agent 系统的运行成本。**

这是不是浪费？看你算什么账——如果在乎"5/5 完整度 + 冲突识别 + 多角度"，多花 280K 换这些质量提升是合理的。如果只在乎"能跑通"，单 Agent 200K 就够。

---

## 四、五个反模式

### 反模式 1：任务本身串行，硬拆多 Agent

A 的输出是 B 的输入，B 的输出是 C 的输入——没有并行收益，只增加通信成本。**用单 Agent 的多步 prompt 就行。**

### 反模式 2：Worker 需要频繁同步

N 个 worker 每隔几秒就要互相同步状态——同步的通信成本可能超过并行的收益。**要么把任务真的拆独立，要么压根不要拆。**

### 反模式 3：单 Agent 装得下，没必要拆

总上下文 < 30K token，单 Agent 完全装得下。经验法则：**< 30K 单 Agent；30K-100K 单 Agent + SubAgent；> 100K 才考虑多 Agent 团队。**

### 反模式 4：多 Agent 当 KPI 用

"上多 Agent"成了目标而不是手段。Demo 里展示"我们用了 8 个 Agent 协作"。**诚实评估任务是否同时满足三个条件。**

### 反模式 5：把多 Agent 当成更好 prompt 的替代

单 Agent prompt 写不好，于是上多 Agent 期望"自动协作能解决问题"。**prompt 没写好的问题，多 Agent 化只会让问题分散到 N 个地方。**

---

## 五、折中方案：单 Agent + SubAgent

很多场景，**完整多 Agent 团队是过度设计，但纯单 Agent 又确实不够**。最佳方案往往是 SubAgent 临时调用。

配套代码在 [multi-agent-07-boundaries.py](./multi-agent-07-boundaries.py)，核心是 `MainAgent` 类：

```python
class MainAgent:
    """单 Agent + 按需召唤 SubAgent。决策权一直在主 Agent。"""

    def run(self, question: str) -> str:
        topics = self._plan(question)

        # 召唤搜索 SubAgent（可并行）
        summaries = {}
        with ThreadPoolExecutor(max_workers=len(topics)) as pool:
            futs = {pool.submit(search_subagent, t): t for t in topics}
            for f in as_completed(futs):
                summaries[futs[f]] = f.result()

        # 主 Agent 自己整合（不需要 writer SubAgent）
        report = self._draft(question, summaries)

        # 召唤 critic SubAgent（最多 2 轮）
        for rnd in range(2):
            issues = critic_subagent(report)
            critical = [i for i in issues if i.get("severity") in ("critical", "major")]
            if not critical:
                break
            report = self._revise(question, summaries, report, issues)

        return report
```

这种模式的本质：

- **没有"团队"**——没有持久的多 Agent 关系
- **有"临时帮手"**——主 Agent 在需要时召唤 SubAgent，用完就放
- **没有共享状态**——SubAgent 完全独立，结果以参数形式返回
- **没有复杂编排**——流程都在主 Agent 心里

### 5.1 跑起来

```bash
OPENAI_API_KEY=... python multi-agent-07-boundaries.py
```

### 5.2 对比

| 维度 | 完整多 Agent 团队 | 单 Agent + SubAgent |
|------|-------------------|---------------------|
| 工程量 | 高（500+ 行） | 中（150-200 行） |
| 调试难度 | 难 | 中 |
| Token 开销 | 高 | 中 |
| 可控性 | 中 | 高 |

经验上，**这个模式能解决约 70% 看起来"需要多 Agent"的问题**。

---

## 六、什么时候多 Agent 真的值得

三个条件全满足才用完整多 Agent 团队：

| 条件 | 含义 | 调研 demo 是否满足 |
|------|------|-------------------|
| 任务可并行 | 子任务之间没有时序依赖 | 是——5 个方案的调研互不依赖 |
| 视角需多样 | 单视角输出不够，需要互相校验 | 是——需要 critic 对抗"被信息源带偏" |
| 上下文需隔离 | 子任务的 context 塞一起会爆 | 是——5 个方案的资料加起来几十 K |

**只满足 1 个**：单 Agent + 多步 prompt。
**满足 2 个**：单 Agent + SubAgent。
**满足 3 个**：完整多 Agent 团队。

---

## 七、终章思考：多 Agent 不是终点

诚实地说：**多 Agent 系统是当前阶段的产物，不是终极形态**。

| 趋势 | 影响 |
|------|------|
| 模型上下文越来越长（200K → 1M+） | "上下文隔离"的动机被稀释 |
| 模型自身 plan-and-execute 越来越强 | "视角多样"部分被模型内化 |
| 工具调用并行化（parallel tool calls） | "必须多 Agent 才能并行"的论点变弱 |

多 Agent 会**收敛到真正需要它的场景**：长任务（小时级到天级）、跨域协作（每个 Agent 是真正的领域专家）、异构模型协作、多智能体仿真。而调研、代码生成、客服这类场景，**未来大概率会回归单 Agent**。

---

## 一句话总结（也是整个系列的总结）

多 Agent 不是更高级的单 Agent，而是**对一类特殊场景的针对性设计**。判断标准：**任务可并行 + 视角需多样 + 上下文需隔离**——三个条件同时满足才值得做完整多 Agent 团队。只满足两个的，单 Agent + SubAgent 更划算。最重要的反常识：**多 Agent 系统的代码量里，工程税远大于逻辑税**——一个 100 行能讲清楚的想法，落到生产级实现是 500 行。这是你做选择前应该有的预期。

---

*配套代码 [multi-agent-07-boundaries.py](./multi-agent-07-boundaries.py) 演示单 Agent + SubAgent 折中方案，约 195 行。整个系列的完整多 Agent 版本约 570 行。*

---

*「从零开始做 Multi-Agent 系统」系列建立在 [从零开始理解 Agent](../../agent/README.md) 之上。如果你还没读过 Agent 系列，建议从 [Agent 系列第一篇](../../agent/01-essence/agent-essence.md) 开始。*
