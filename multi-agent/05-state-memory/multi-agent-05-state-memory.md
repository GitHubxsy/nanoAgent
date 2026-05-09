# 从零开始做 Multi-Agent 系统（五）：状态、记忆与上下文——每个 Agent 自带 vs 共享

> **「从零开始做 Multi-Agent 系统」系列** —— 第五篇。前四章搭起了能稳定跑出完整报告的多 Agent 系统。但跑几次后会发现诡异的现象——5 个 Searcher 都搜了同一篇论文、报告里出现两个对立结论。这一章解决"状态与共享"的问题。
>
> - [第一篇：什么时候单 Agent 不够](../01-when-single-agent-fails/multi-agent-01-when-single-agent-fails.md)
> - [第二篇：最小多 Agent 骨架](../02-minimum-skeleton/multi-agent-02-minimum-skeleton.md)
> - [第三篇：Agent 之间怎么传话](../03-communication/multi-agent-03-communication.md)
> - [第四篇：编排模式之争](../04-orchestration/multi-agent-04-orchestration.md)
> - **第五篇：状态、记忆与上下文**（本文）
> - [第六篇：错误传播、重试与可观测性](../06-failure-trace/multi-agent-06-failure-trace.md)
> - [第七篇：边界与反模式](../07-boundaries/multi-agent-07-boundaries.md)

---

## 一、先说结论

| 状态层 | 归属 | 存什么 | 生命周期 |
|--------|------|--------|---------|
| 短期 context | 每个 Agent 自己 | 对话历史、搜索记录 | 任务结束即丢 |
| 长期记忆 | 每个 Agent 自己 | 跨任务积累的知识 | 持久化 |
| **共享 state** | **所有 Agent 可见** | **已 claim 的 topic、已抓的 URL、关键论断** | **任务级** |

一句话总结：**共享事实，不共享判断**。事实层（URL、topic 名）让 worker 自由读写解决去重；判断层（哪个更好、哪段可信）只在汇总阶段访问，避免 worker 互相"洗脑"。

---

## 二、开场：一份诡异的报告

把第四章的混合方案跑 5 次，每次输出都成形了。但仔细读这 5 份报告，你会发现一些奇怪的事：

**怪事 1：重复劳动**——FlashAttention 和 PagedAttention 的 Searcher 都去读了同一篇 PagedAttention 论文，重复了近一倍的 `web_read` 调用。

**怪事 2：对立结论并存**——报告里同时出现两段话：

> "FlashAttention 在长上下文场景下速度领先，比 PagedAttention 快约 2.3 倍。"
>
> ……（隔了几段）……
>
> "PagedAttention v2 在长上下文场景下表现更优，相比 FlashAttention 提速约 1.8 倍。"

两段都引用了真实的博客——但一篇是 FlashAttention 团队 2024 年发的、另一篇是 vLLM 团队 2025 年发的。**两个 worker 各自查到了支持自己结论的资料，没人发现它们冲突**。

**怪事 3：Writer 不察觉矛盾**——Writer 收到的是 5 份独立摘要，没有整体视角，原封不动把对立结论都写进去了。

根源是同一个：**每个 Agent 都活在自己的小世界里，没有"共享视图"**。第二章我们刻意让 worker 完全独立——这是好的起点，但代价就是上面这些症状。

---

## 三、Agent 的三层状态

先把"状态"这个概念拆细。多 Agent 系统里有三层不同的状态：

### 3.1 短期 context（per-Agent）

每个 Agent 自己的对话历史。比如 `Searcher_FlashAttention` 读了哪些 URL、模型说过什么。数据量大（几十 K token 起步），仅 Agent 自己用，任务结束就丢。

### 3.2 长期记忆（per-Agent persistent）

某个 Agent 跨任务保留的知识。比如"上次调研 vLLM 时发现官方文档结构是这样"。调研 demo 里**暂时不需要这一层**——每次调研都是独立的。但在客服 Agent、长程项目 Agent 里这层很关键。

### 3.3 跨 Agent 共享 state

所有 Agent 可见的全局信息。数据量小（几百 token 到几 K），多个 Agent 读写，任务级生命周期。

> **关键洞察**：**这一层是这章的主角**。前面的三个怪事，都因为缺这一层。

---

## 四、共享状态怎么解决三个怪事

### 4.1 去重：fetched_urls

加一个"已搜过的 URL"集合到共享状态里。每个 Searcher 在 `web_read` 之前先检查：

```python
def web_read_dedup(url, scratch: Scratchpad):
    if scratch.is_fetched(url):
        return f"[cached] {MOCK_PAGES.get(url, '')[:3000]}"
    time.sleep(0.5)
    scratch.record_url(url)
    return MOCK_PAGES.get(url, "(not found)")[:5000]
```

效果：PagedAttention 论文从被读 2 次降到 1 次，整体 `web_read` 次数减少 ~25%。

### 4.2 冲突识别：key_findings + conflict detector

每个 Searcher 在生成摘要时把"关键论断"挂到 scratchpad 上。然后引入一个轻量的 conflict detector——不一定是独立 Agent，一次 LLM 调用就行：

```python
def detect_conflicts(scratch: Scratchpad):
    findings = scratch.snapshot_for_writer()["key_findings"]
    if not findings:
        return []
    flat = [{"topic": t, **f} for t, fs in findings.items() for f in fs]
    prompt = ("以下是从多个来源摘出的论断。找出**互相矛盾**的论断对。\n"
              "每对返回：{a, b, why_conflict, possible_reason}（JSON 数组）。\n\n"
              + json.dumps(flat, ensure_ascii=False))
    text = (llm([{"role": "user", "content": prompt}]).content or "")
    # ... 解析 JSON ...
```

跑出来的冲突报告会标注时间差、测试场景差异和立场偏差，Writer 就能在报告里明确说明分歧。

### 4.3 整体视角

Writer 之前只能看到 5 份独立摘要。现在它额外能看到 `key_findings` 和冲突报告，**整合时就有了"上帝视角"**——能跨 worker 比对、能识别冲突、能调整结构。

---

## 五、给 demo 加 Scratchpad

配套代码在 [multi-agent-05-state-memory.py](./multi-agent-05-state-memory.py)，核心是 `Scratchpad` 类。

### 5.1 Scratchpad 实现

```python
class Scratchpad:
    """所有 Agent 可访问的共享便签。区分事实层和判断层。"""

    def __init__(self):
        self._lock = threading.RLock()
        # 事实层：worker 自由读写
        self.claimed_topics: set[str] = set()
        self.fetched_urls: set[str] = set()
        # 判断层：worker 只写，Writer 阶段才读
        self.key_findings: dict[str, list[dict]] = {}
        self.conflicts: list[dict] = []

    def claim(self, topic):
        with self._lock:
            if topic in self.claimed_topics:
                return False
            self.claimed_topics.add(topic)
            return True

    def is_fetched(self, url):
        with self._lock:
            return url in self.fetched_urls

    def record_url(self, url):
        with self._lock:
            self.fetched_urls.add(url)

    def snapshot_for_writer(self):
        """Writer 启动时拿到的快照，只读副本。"""
        with self._lock:
            return {"key_findings": dict(self.key_findings),
                    "conflicts": list(self.conflicts)}
```

设计要点：

| 层级 | 字段 | 谁写 | 谁读 | 作用 |
|------|------|------|------|------|
| 事实层 | `claimed_topics` | Searcher | Searcher | 防重复认领 |
| 事实层 | `fetched_urls` | Searcher | Searcher | 防重复抓取 |
| 判断层 | `key_findings` | Searcher | Writer | 冲突检测素材 |
| 判断层 | `conflicts` | Detector | Writer | 冲突说明 |

### 5.2 接入主流程

```python
def run(q):
    scratch = Scratchpad()
    topics = planner(q)

    # 并行搜索，每个 Searcher 带 scratchpad 引用
    summaries = {}
    with ThreadPoolExecutor(max_workers=len(topics)) as pool:
        futs = {pool.submit(searcher, t, scratch): t for t in topics}
        for f in as_completed(futs):
            summaries[futs[f]] = f.result()

    # Writer 之前做一次冲突检测
    conflicts = detect_conflicts(scratch)

    # Writer 拿到摘要 + scratchpad 快照
    report = writer(q, summaries, scratch)
    return report
```

### 5.3 跑起来

```bash
OPENAI_API_KEY=... python multi-agent-05-state-memory.py
```

---

## 六、共享状态的代价

引入 scratchpad 看起来全是收益。但跑多了会发现**只有共享状态才有的新问题**：

| 代价 | 表现 | 应对 |
|------|------|------|
| 后来者被"洗脑" | Searcher_PA 看到 FA 的 findings 后，输出不自觉向"对照 FA"倾斜 | 分事实层/判断层——**判断层 worker 不读** |
| 竞态 | 多 worker 并发写 `key_findings` | `threading.RLock`；分布式场景用 Redis 事务 |
| 黑板膨胀 | scratchpad 字段越加越多，变成塞满杂物的全局变量 | 按命名空间组织，定期清理无人消费的字段 |
| 独立测试变难 | 单独跑一个 Searcher 需要 mock 整个 scratchpad | 这是引入共享状态的工程税 |

> **关键洞察**：**共享越多，Agent 之间的"独立视角"就被腐蚀越多**。这是个隐蔽的失败模式——不是报错，而是结果悄悄变差。

---

## 七、三条经验法则

### 法则 1：能不共享就不共享

每加一个 scratchpad 字段都要回答"这个字段如果不共享，会让什么问题不可解？"答不上来就别加。

### 法则 2：共享事实，不共享判断

事实（URL、topic 名、文件路径）共享了不会污染 Agent 视角。判断（哪个方案更好、哪段资料更可信）共享了会立刻腐蚀独立性。

经验：**判断层只在汇总阶段（Planner / Writer）访问，worker 阶段一律不读**。

### 法则 3：worker 多写、汇总阶段统一读

让 worker 多写一点（比如多记几条 key_findings）成本低。让 worker 都来读它会引入"洗脑"风险。正确姿势是：**worker 只写不读判断层，汇总阶段统一读**。

---

## 八、加完 Scratchpad 后的对比

| 指标 | 第四章末（Workflow + Supervisor） | 第五章末（+ Scratchpad） |
|------|----------------------------------|------------------------|
| web_read 重复率 | 25% | 5% |
| 冲突识别 | 0 个 | 2-3 个识别出 + 报告说明 |
| 报告深度 | 高 | 高 + 多角度（含冲突说明） |

报告质量肉眼可见地变好了。但还有几个问题没解决：

| 问题 | 表现 | 哪章解决 |
|------|------|---------|
| 错误处理缺失 | 某个 Searcher 跑挂了，整个调研结果残缺 | [第六篇](../06-failure-trace/multi-agent-06-failure-trace.md) |
| 没有 critic 视角 | 只检测冲突，不主动质疑摘要本身 | [第六篇](../06-failure-trace/multi-agent-06-failure-trace.md) |
| 不可观测 | 跑偏了不知道为什么，调试靠肉眼 | [第六篇](../06-failure-trace/multi-agent-06-failure-trace.md) |

---

## 一句话总结

多 Agent 系统的状态分三层：每个 Agent 的 context、Agent 的长期记忆、跨 Agent 的共享 state。前两层是"私域"，第三层是"公域"。公域的边界要严格——**共享事实，不共享判断**。完全独立的 Agent 比看起来更慢更贵；过度共享的 Agent 又会"集体跑偏"——共享什么必须想清楚。

---

## 下一篇预告

加完 scratchpad 后 demo 大部分时候能跑出完整报告。但还是有概率出现各种崩溃：worker 超时、API 限流、模型给的 JSON 格式不对、共享状态死锁。

[下一篇](../06-failure-trace/multi-agent-06-failure-trace.md)处理多 Agent 系统真正难的部分：**当一个 Agent 跑挂了，整个系统怎么办？** 加 critic Agent 主动质疑、加重试策略、加 trace 可视化——多 Agent 系统不可观测就约等于不可用。

---

*配套代码 [multi-agent-05-state-memory.py](./multi-agent-05-state-memory.py) 在第四版基础上新增 Scratchpad + conflict detector，约 240 行。*
