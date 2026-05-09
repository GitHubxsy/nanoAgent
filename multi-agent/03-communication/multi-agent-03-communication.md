# 从零开始做 Multi-Agent 系统（三）：Agent 之间怎么传话——消息、共享状态、文件

> **「从零开始做 Multi-Agent 系统」系列** —— 第三篇。上一章搭起了第一版骨架：Planner + N Searchers + Writer。Searcher 把字符串摘要交回 Planner——简单，但不够用。这一章讨论一个基础但容易被低估的问题：**Agent 之间到底用什么传数据？**
>
> - [第一篇：什么时候单 Agent 不够](../01-when-single-agent-fails/multi-agent-01-when-single-agent-fails.md)
> - [第二篇：最小多 Agent 骨架](../02-minimum-skeleton/multi-agent-02-minimum-skeleton.md)
> - **第三篇：Agent 之间怎么传话**（本文）
> - [第四篇：编排模式之争](../04-orchestration/multi-agent-04-orchestration.md)
> - [第五篇：状态、记忆与上下文](../05-state-memory/multi-agent-05-state-memory.md)
> - [第六篇：错误传播、重试与可观测性](../06-failure-trace/multi-agent-06-failure-trace.md)
> - [第七篇：边界与反模式](../07-boundaries/multi-agent-07-boundaries.md)

---

## 一、先说结论

| 通信方式 | 适合传什么 | 不适合传什么 |
|---------|-----------|------------|
| 消息（Message） | 控制信号：任务、参数、状态码、路径 | 长内容（会撑爆 context） |
| 文件（File） | 产出：资料、摘要、报告 | 控制流（太重） |
| 共享状态（Shared State） | 协调：已 claim 的 topic、全局进度 | 大数据（读写放大） |

一句话总结：**不是三选一，而是三件事各管一摊**——消息传控制信号，文件传产出，共享状态做协调。最常见的反模式是"全用消息"，简单直觉但 context 会爆。

---

## 二、第二章留下的问题

第二章的骨架里，Searcher 给 Planner 交回的是一段字符串摘要。跑了几次后发现不对劲：

1. **Writer 想引用原文**——摘要只是 worker 总结的几句话，原文拿不到
2. **几个 worker 搜到了同一篇论文**——每个都自己摘要一遍，重复成本高
3. **某个 worker 跑了 10 分钟挂掉**——10 分钟的工作全没了
4. **出问题了想看 worker 搜了什么**——工作过程全在调用栈里，看不到

这些问题的共同根源：**字符串摘要只是 worker 的"压缩快照"，不是它的"完整产出"**。

---

## 三、三种通信方式

### 3.1 消息（Message Passing）

最直觉的方式——一个 Agent 完成后，结果作为参数传给下一个：

```python
summary = searcher.run(topic)
report = writer.run(summary)
```

- ✅ 语义清晰，像函数调用
- ✅ 没有副作用，调试容易
- ❌ 全在 context 里——长内容撑爆下游 Agent
- ❌ 无法保留工作过程

### 3.2 共享状态（Shared State / Blackboard）

所有 Agent 读写同一份数据，像一块黑板：

```python
shared_state = SharedState()
shared_state.claimed_topics  # 哪些 topic 已经在做
shared_state.fetched_urls    # 哪些 URL 已经抓过
shared_state.errors          # 哪个 topic 出错了
```

- ✅ 所有 Agent 都能看到全局状态，容易做去重和协调
- ❌ 并发读写有竞态，需要锁
- ❌ 状态膨胀后，"读哪一部分"成了新问题

### 3.3 文件（File-based）

Agent 把产出写到磁盘，下游按需读：

```python
def searcher_run(topic):
    findings = do_search(topic)
    Path(f"work/raw/{topic}.md").write_text(findings)       # 完整资料
    Path(f"work/summary/{topic}.md").write_text(summarize(findings))  # 摘要
    return f"work/summary/{topic}.md"   # 只传路径
```

- ✅ 持久化——worker 挂了，已写的文件还在
- ✅ 路径在消息里，内容按需加载，不撑爆 context
- ✅ 人也能直接打开看（调试友好）
- ❌ 文件命名、清理需要规范

### 3.4 对比总结

| 维度 | 消息 | 共享状态 | 文件 |
|------|------|---------|------|
| token 成本 | 高（全在 context） | 中 | 低（只传路径） |
| 大数据传输 | ✗ 容易爆 | ✗ 读时爆 | ✓ 友好 |
| 持久化 | ✗ | △ | ✓ 默认有 |
| 并发安全 | ✓（无共享） | ✗（需锁） | △（文件粒度隔离） |
| 调试便利 | △ | ✗ | ✓（直接看文件） |
| 适用场景 | 短数据、控制流 | 协调、去重 | 大数据、产物 |

> **关键洞察**：消息适合传"控制信号"，一旦数据超过几 K token 就扛不住。共享状态适合"协调"，不适合存大数据。文件适合"产出"——**把路径作为消息传，内容存在文件里，两者互补**。

---

## 四、给 demo 选定方案

回到调研 demo，三种方式各管一摊：

| 通信环节 | 方式 | 传什么 |
|---------|------|-------|
| Planner → Searcher | 消息 | topic 名称 |
| Searcher 产出 | 文件 | `work/raw/{topic}.md` + `work/summary/{topic}.md` |
| Searcher → Planner | 消息 | 摘要文件路径 |
| Planner → Writer | 消息 | 摘要路径列表 |
| 全局协调 | 共享状态 | `claimed_topics`、`fetched_urls`、`errors` |

### 4.1 核心代码

配套代码在 [multi-agent-03-communication.py](./multi-agent-03-communication.py)，关键变化是 `SharedState` 和文件 I/O：

```python
class SharedState:
    """协调用的全局状态。只放小元数据，不放大内容。"""
    def __init__(self):
        self._lock = threading.RLock()
        self.claimed_topics: set[str] = set()
        self.fetched_urls: set[str] = set()
        self.errors: dict[str, str] = {}

    def claim(self, topic: str) -> bool:
        with self._lock:
            if topic in self.claimed_topics:
                return False
            self.claimed_topics.add(topic)
            return True
```

`claim()` 用锁保证原子性——两个 worker 同时 claim 同一个 topic 时，只有一个能成功。

Searcher 的变化——同时写原始资料和摘要两份文件：

```python
def searcher(topic, state):
    if not state.claim(topic):
        return {"topic": topic, "skipped": True}

    raw_path = RAW_DIR / topic.replace(" ", "_")
    summary_path = SUMMARY_DIR / f"{topic.replace(' ', '_')}.md"

    # ... Agent 循环：搜索 + 阅读 + 总结 ...

    summary_path.write_text(summary)
    return {"topic": topic, "summary_path": str(summary_path)}
```

Writer 按路径读摘要文件：

```python
def writer(question, summary_paths):
    summaries = {Path(p).stem: Path(p).read_text() for p in summary_paths}
    # ... 整合写报告 ...
```

### 4.2 跑起来

```bash
OPENAI_API_KEY=... python multi-agent-03-communication.py
```

运行后 `work/` 目录的结构：

```
work/
├── raw/                    # 每个 topic 的原始资料
│   ├── FlashAttention/
│   ├── PagedAttention/
│   └── ...
├── summary/                # 每个 topic 的摘要
│   ├── FlashAttention.md
│   ├── PagedAttention.md
│   └── ...
└── report-multi-v3.md      # 最终报告
```

---

## 五、为什么不全用消息

早期的多 Agent 框架（CrewAI / AutoGen 早期版本）默认全用消息。然后大家踩了同样的坑：

### 5.1 Context 传一倍

Searcher 摘要 5K token，5 个 worker 就 25K。全塞进 Writer 的 context——加上 prompt 和 question，Writer 启动时 context 已占 40K。改成"路径 + 按需读"，启动时 < 5K。

### 5.2 长程依赖断链

Writer 写到一半需要某篇论文的具体段落。消息方案下原文已丢；文件方案下 `read_file("work/raw/FlashAttention.md")` 直接拿到。

### 5.3 失败不可恢复

5 个 worker 跑了 7 分钟，第 5 个挂了。消息方案下前 4 个结果在调用栈里——异常退出就丢了。文件方案下已完成的 4 份摘要还在磁盘上，**重跑只需跑第 5 个**。

### 5.4 调试看不到过程

消息方案下 worker 的工作过程都在 LLM 调用栈里。文件方案下——直接打开 `work/raw/{topic}.md` 就能看到 Searcher 搜了什么。

---

## 六、通信的失败模式

引入文件 + 共享状态后，也引入了新的失败模式：

| 失败模式 | 场景 | 应对 |
|---------|------|------|
| 文件路径冲突 | 两个 worker 同时写同一路径 | 用 worker_id 做命名空间隔离 |
| 共享状态竞态 | 两个 worker 同时 claim 同一 topic | `claim()` 加锁，原子化 |
| 文件没写完就被读 | Searcher 写到一半，Writer 开始读 | 原子写：先写临时文件，`rename` 到目标 |
| 清理不干净 | 上次的文件混进这次的结果 | 每次启动前清空或归档到时间戳目录 |

这些都是工程问题，不复杂——但不处理就会变成玄学 bug。

---

## 一句话总结

多 Agent 的通信不是"消息 vs 文件 vs 共享状态"三选一，而是**三件事各管一摊**：消息传控制信号，文件传产出，共享状态做协调。最常见的反模式是"全用消息"——一旦 worker 产出超过 5K token，就该把内容搬到文件里，消息只传路径。

---

## 下一篇预告

通信方式定了，但"怎么把消息接力起来"还没定。第二版的执行图是固定 DAG：Planner → Searcher × N → Writer——这叫 **Workflow** 模式。

但还有别的选择：让 Planner 一直在场，每轮决定下一步——**Supervisor** 模式；或者完全去中心化，Agent 之间自主路由——**Swarm** 模式。

[下一篇](../04-orchestration/multi-agent-04-orchestration.md)用三种模式各重写一遍 demo，看哪种最适合调研场景。剧透：**Swarm 看起来最 AI，但生产环境几乎没人用**。

---

*配套代码 [multi-agent-03-communication.py](./multi-agent-03-communication.py) 在第二版基础上新增 SharedState + 文件 I/O，累计约 200 行。*
