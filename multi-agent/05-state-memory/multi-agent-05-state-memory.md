# 从零开始做 Multi-Agent 系统（五）：状态、记忆与上下文——每个 Agent 自带 vs 共享

> **「从零开始做 Multi-Agent 系统」系列** —— 第五篇。前四章我们搭起了能稳定跑出 5/5 完整度报告的多 Agent 系统。但跑几次后会发现一些诡异的现象——5 个 Searcher 都搜了同一篇论文、报告里出现两个对立结论。这一章解决"状态与共享"的问题。
>
> - [第一篇：什么时候单 Agent 不够](../01-when-single-agent-fails/)
> - [第二篇：最小多 Agent 骨架](../02-minimum-skeleton/)
> - [第三篇：Agent 之间怎么传话](../03-communication/)
> - [第四篇：编排模式之争](../04-orchestration/)
> - **第五篇：状态、记忆与上下文**（本文）
> - 第六篇：错误传播、重试与可观测性（即将更新）
> - ...

---

## 开场：一份诡异的报告

把第四章的混合方案跑 5 次，每次输出都成形了。但仔细读这 5 份报告，你会发现一些奇怪的事：

**怪事 1：FlashAttention 部分和 PagedAttention 部分都引用了同一篇 PagedAttention 论文**——而且引用上下文不一致：FlashAttention 的 Searcher 用它来说"PagedAttention 的内存管理思路"，PagedAttention 的 Searcher 用它来说"PagedAttention 的核心算法"。**两个 worker 都跑去读了同一篇论文**，重复了几乎一倍的 web_read 调用。

**怪事 2：报告里同时出现两段对立的话**：

> "FlashAttention 在长上下文场景下速度领先，比 PagedAttention 快约 2.3 倍。"
>
> ……（隔了几段）……
>
> "PagedAttention v2 在长上下文场景下表现更优，相比 FlashAttention 提速约 1.8 倍。"

**两段都引用了真实的博客**——但一篇是 FlashAttention 团队 2024 年发的、另一篇是 vLLM 团队 2025 年发的。**两个 worker 各自查到了支持自己结论的资料，没人发现它们冲突**。

**怪事 3：Writer 整合的时候原封不动把两段都写进去了**。Writer 没有"整体视角"——它收到的是 5 份独立摘要，没办法察觉 5 份之间的矛盾。

---

这些怪事的根源是同一个：**每个 Agent 都活在自己的小世界里，没有"共享视图"**。

第二章我们刻意让 worker 完全独立——这是个好的起点，但代价就是上面这些症状。这一章解决方法是引入**共享状态**——但要小心"过度共享"会引入新的问题。

---

## 一、Agent 的三层状态

先把"状态"这个抽象概念拆细。一个多 Agent 系统里其实有三层不同的状态：

### 第一层：短期 context（per-Agent）

每个 Agent 自己的对话历史。比如 `Searcher_FlashAttention` 在它的循环里读了哪些 URL、模型说过什么。

特点：
- 数据量大（几十 K token 起步）
- 仅 Agent 自己用
- 任务结束就丢

### 第二层：长期记忆（per-Agent persistent）

某个 Agent 跨任务保留的知识。比如"上次调研 vLLM 时发现它官方文档结构是这样"。

特点：
- 数据量中等
- 仅 Agent 自己用
- 跨任务复用

调研 demo 里**暂时不需要这一层**——每次调研都是独立的。但在客服 Agent、长程项目 Agent 里这层很关键。

### 第三层：跨 Agent 共享 state

所有 Agent 可见的全局信息。比如"已经被 claim 的 topic 列表"、"所有已发现的关键论文 URL"。

特点：
- 数据量小（几百 token 到几 K）
- 多个 Agent 读写
- 任务级生命周期

**这一层是这一章的主角**。前面提到的所有怪事，都因为缺这一层。

---

## 二、共享状态解决什么

回到前面三个怪事，看共享状态怎么解。

### 解怪事 1：去重

加一个"已搜过的 URL"集合到共享状态里：

```python
shared_state = {
    "claimed_topics": set(),
    "fetched_urls": set(),       # ← 新增：所有 worker 已抓过的 URL
    "key_findings": {},          # ← 新增：每个 worker 提炼的关键发现
}
```

每个 Searcher 在 web_read 之前先检查：

```python
def fetch_with_dedup(url):
    if url in shared_state["fetched_urls"]:
        # 别人已经抓过了，直接复用
        return Path(url_to_path(url)).read_text()

    content = web_read(url)
    Path(url_to_path(url)).write_text(content)
    shared_state["fetched_urls"].add(url)
    return content
```

效果：跑一次 demo，PagedAttention 论文从被读 2 次降到 1 次。整体 web_read 次数减少 ~25%。

### 解怪事 2：冲突识别

加一个 `key_findings` 字段，每个 Searcher 在生成摘要前把"关键论断"挂上去：

```python
shared_state["key_findings"][topic] = [
    {"claim": "FlashAttention-3 在 H100 上比 v2 快 1.5x", "source": "..."},
    {"claim": "FlashAttention 在长上下文场景下比 PagedAttention 快 2.3x", "source": "..."},
]
```

然后引入一个轻量的 conflict-detector（不一定是独立 Agent，可以是简单的 LLM 调用）：

```python
def detect_conflicts(key_findings_dict):
    # 把所有 claim 摆出来，让 LLM 找冲突
    all_claims = flatten(key_findings_dict)
    return llm_call(
        f"以下论断是不是有相互矛盾的？\n{all_claims}\n"
        "如果有冲突，列出冲突对和可能原因。"
    )
```

跑出来：

> 检测到冲突：
> - "FlashAttention 比 PagedAttention 快 2.3x"（来源：FlashAttention 团队 2024 博客）
> - "PagedAttention v2 比 FlashAttention 快 1.8x"（来源：vLLM 团队 2025 博客）
>
> 可能原因：
> 1. 两份资料发布时间相隔约 1 年，PagedAttention 期间有 v2 大版本升级
> 2. 测试场景不同（FlashAttention 测的是 8K 上下文，PagedAttention v2 测的是 32K）
> 3. 两者均出自实现方自己的 benchmark，立场可能有偏差

把冲突说明传给 Writer，Writer 在报告里这么写：

> "在长上下文场景下，FlashAttention 和 PagedAttention v2 的相对性能存在争议。早期 benchmark（2024 年，FlashAttention 团队）显示 FlashAttention 占优；较新的 benchmark（2025 年，vLLM 团队）则显示 PagedAttention v2 在 32K+ 上下文场景反超。建议读者根据自己的实际场景做对比。"

报告质量上一个台阶。

### 解怪事 3：整体视角

Writer 之前只能看到 5 份独立摘要。现在它额外能看到 `key_findings` 和冲突报告，**整合时就有了"上帝视角"**——能跨 worker 比对、能识别冲突、能调整结构。

---

## 三、给 demo 加 shared scratchpad

把上面这些落到代码层面。我们引入一个 **scratchpad** 模块作为共享状态的实现：

```python
# scratchpad.py
import json
from pathlib import Path
from threading import RLock

class Scratchpad:
    """所有 Agent 可读的共享便签。Planner 可写，worker 受限写。"""

    def __init__(self, path: Path):
        self.path = path
        self.lock = RLock()
        self._state = {
            "claimed_topics": set(),
            "fetched_urls": set(),
            "key_findings": {},
            "conflicts": [],
            "progress": {},
        }

    def claim_topic(self, worker_id: str, topic: str) -> bool:
        with self.lock:
            if topic in self._state["claimed_topics"]:
                return False
            self._state["claimed_topics"].add(topic)
            self._state["progress"][topic] = {"worker": worker_id, "status": "running"}
            return True

    def is_url_fetched(self, url: str) -> bool:
        with self.lock:
            return url in self._state["fetched_urls"]

    def record_fetched(self, url: str):
        with self.lock:
            self._state["fetched_urls"].add(url)

    def add_finding(self, topic: str, claim: str, source: str):
        with self.lock:
            self._state["key_findings"].setdefault(topic, []).append({
                "claim": claim,
                "source": source,
            })

    def record_conflict(self, conflict: dict):
        with self.lock:
            self._state["conflicts"].append(conflict)

    def snapshot_for_writer(self) -> dict:
        """Writer 启动时拿到的快照，只读副本。"""
        with self.lock:
            return {
                "key_findings": dict(self._state["key_findings"]),
                "conflicts": list(self._state["conflicts"]),
            }
```

把它接到 demo 里：

```python
def hybrid_run(question: str) -> str:
    scratchpad = Scratchpad(work_dir / "scratchpad.json")

    topics = planner_node(question)

    # 给每个 topic 派 worker（带 scratchpad 引用）
    summary_paths = parallel_map(
        lambda t: supervised_search(t, scratchpad),
        topics
    )

    # Planner 在 worker 全部完成后做一次冲突检测
    conflicts = detect_conflicts(scratchpad.snapshot_for_writer())
    for c in conflicts:
        scratchpad.record_conflict(c)

    # Writer 拿到摘要 + 完整 scratchpad 视图
    report = writer_node(question, summary_paths, scratchpad.snapshot_for_writer())
    return report
```

---

## 四、共享状态的代价：过度共享会让 Agent 失去独立判断

引入 scratchpad 看起来全是收益。但跑得多了，会发现一些**只有共享状态才有的新问题**。

### 代价 1：后启动的 worker 会被前面 worker 的发现"洗脑"

如果 Searcher_FlashAttention 先跑，往 `key_findings` 里写了"FlashAttention 是当前最快的方案"。后启动的 Searcher_PagedAttention 在做摘要前看到了这条 finding，它的输出会**不自觉地向"对照 FlashAttention"的视角倾斜**——而不是独立评估 PagedAttention。

这是个隐蔽的失败模式：**共享越多，Agent 之间的"独立视角"就被腐蚀越多**。

**应对**：把 scratchpad 分成"事实层"（去重用的 fetched_urls、claimed_topics）和"判断层"（key_findings）。事实层全 worker 共享，判断层默认不让 worker 看到——只在 Planner 和 Writer 阶段访问。

### 代价 2：竞态

多个 worker 并发往 `key_findings` 写，会出现竞态。Python 的 `threading.RLock` 能解决（如上面代码里做的）。但分布式场景下需要 Redis 或者数据库的事务。

### 代价 3："黑板膨胀"

随着任务复杂度上升，scratchpad 上挂的字段会越来越多。最后变成一个塞满杂物的全局变量——所有 Agent 都依赖它、所有 Agent 都不知道里面到底有什么。

**应对**：scratchpad 严格按命名空间组织，加版本控制（每次 schema 变动 bump 版本号），定期清理无人消费的字段。

### 代价 4：让"agent 独立可测试"变难

引入共享状态后，单独跑一个 Searcher 来测试它的逻辑变得复杂——你得 mock 整个 scratchpad。这是引入任何共享状态都要付的工程税。

---

## 五、共享多少才合适？三条经验法则

经过 demo 的多次迭代，给读者三条共享状态的经验法则：

### 法则 1：能不共享就不共享

每加一个 scratchpad 字段都要回答"这个字段如果不共享，会让什么问题不可解？"如果回答不上来，就别加。

### 法则 2：共享"事实"不共享"判断"

事实（URL、topic 名、文件路径）共享了不会污染 Agent 视角。
判断（哪个方案更好、哪段资料更可信）共享了会立刻腐蚀独立性。

经验：**判断层只在汇总阶段（Planner / Writer）访问，worker 阶段一律不读**。

### 法则 3：写 scratchpad 比读它便宜

让 worker 多写一点（比如多记几条 key_findings）成本低，让 worker 都来读它会引入"洗脑"风险。

所以正确姿势是：**worker 多写、汇总阶段统一读**——而不是让 worker 之间互相窥探彼此的状态。

---

## 六、Demo 的当前状态

加完 scratchpad 后，跑一次 demo：

| 指标 | 第四章末（Workflow + Supervisor） | 第五章末（+ Scratchpad） |
|------|----------------------------------|------------------------|
| 总耗时 | 14 分钟 | 13 分钟（去重省了一些） |
| 总 token | 380K | 350K |
| web_read 重复率 | 25% | 5% |
| 冲突识别 | 0 个识别出的 | 2-3 个识别出 + 报告里说明 |
| 报告深度 | 高 | 高 + 多角度（含冲突说明） |

报告质量肉眼可见地变好了。但还有几个问题没解决：

1. **某个 Searcher 跑挂了，整个调研结果残缺**——还没做错误处理
2. **没有 critic 视角批判摘要本身**——目前只是检测冲突，没有"主动质疑"
3. **跑偏了不知道为什么**——没有 trace，调试靠肉眼

这些是下一章的工作。

---

## 一句话总结

多 Agent 系统的状态分三层：每个 Agent 的 context、Agent 的长期记忆、跨 Agent 的共享 state。前两层是"私域"，第三层是"公域"。

公域的边界要严格：**共享事实，不共享判断**。事实层（URL、claim 列表）让 worker 自由读写解决去重和冲突识别；判断层（哪个更好、哪段可信）只在汇总阶段访问，避免 worker 互相"洗脑"。

完全独立的 Agent 比看起来更慢更贵；过度共享的 Agent 又会"集体跑偏"——共享什么必须想清楚。

---

## 下一篇预告

加完 scratchpad 后 demo 的稳定版本能跑出 5/5 完整度的报告。但**只是大部分时候**——还是有 1/5 的概率出现某种崩溃：worker 超时、API 限流、模型给的 JSON 格式不对、共享状态死锁。

下一章我们处理多 Agent 系统真正难的部分：**当一个 Agent 跑挂了，整个系统怎么办？** 加一个 critic Agent 来主动质疑、加重试策略、加 trace 可视化。

trace 是这一章的另一个重头戏——**多 Agent 系统不可观测就约等于不可用**。

---

*这一章新增 ~120 行代码（scratchpad + conflict detector + 接入），累计 ~370 行。*
