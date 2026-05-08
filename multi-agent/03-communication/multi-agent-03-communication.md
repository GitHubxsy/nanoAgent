# 从零开始做 Multi-Agent 系统（三）：Agent 之间怎么传话——消息、共享状态、文件

> **「从零开始做 Multi-Agent 系统」系列** —— 第三篇。第二章我们搭起了第一版骨架：1 个 Planner + N 个 Searcher + 1 个 Writer，让 Searcher 把字符串摘要交回 Planner。这一章讨论一个基础但容易被低估的问题——**Agent 之间到底用什么传话**。
>
> - [第一篇：什么时候单 Agent 不够](../01-when-single-agent-fails/)
> - [第二篇：最小多 Agent 骨架](../02-minimum-skeleton/)
> - **第三篇：Agent 之间怎么传话**（本文）
> - 第四篇：编排模式之争（即将更新）
> - ...

---

## 开场：摘要之外，Searcher 还有什么要交回去？

第二章的第一版骨架里，Searcher 给 Planner 交回的是一段字符串摘要：

> "FlashAttention-3 在 H100 上比 v2 快 1.5x，主要改进是异步 Tensor Core 调度。关键论文：[FlashAttention-3 paper, 2024]。社区采用度高，已集成到 vLLM 和 SGLang。"

跑了几次后你发现一些不对劲的地方：

1. **Writer 想引用原文具体段落，拿不到**——摘要只是 worker 总结的几句话
2. **几个 worker 都搜到了 PagedAttention 的论文**，每个都自己摘要一遍，**重复成本高**
3. **某个 worker 跑了 10 分钟挂掉了**，10 分钟的工作全没了
4. **Writer 想看 worker 的"工作过程"**（搜了什么、读了什么、为什么这么总结），全看不到

这些问题的共同根源是：**字符串摘要只是 worker 工作的"压缩快照"，而不是它的"完整产出"**。

要解决这些问题，得回到一个更基础的问题：**Agent 之间到底应该用什么传数据？**

---

## 一、三种主流通信方式

业界目前主要用三种通信方式。先把它们摆出来：

### 方式 1：消息（Message Passing）

**最直觉的方式**。一个 Agent 完成任务后，把结果作为参数传给下一个 Agent：

```python
# 消息：直接传字符串/字典
summary = searcher.run(topic)
report = writer.run(summary)
```

特点：
- ✅ 语义清晰，像函数调用
- ✅ 没有副作用，调试容易
- ❌ 数据全在 context 里——长内容会把下游 Agent 的 context 撑爆
- ❌ 无法保留"工作过程"——只有最终结果传下去

### 方式 2：共享状态（Shared State / Blackboard）

**所有 Agent 读写同一份数据**，像一块共享的黑板：

```python
# 共享状态
shared_state = {
    "topics": [...],
    "summaries": {...},
    "raw_findings": {...}
}

def searcher_run(topic):
    findings = do_search(topic)
    shared_state["raw_findings"][topic] = findings  # 写
    shared_state["summaries"][topic] = summarize(findings)

def writer_run():
    summaries = shared_state["summaries"]  # 读
    return write_report(summaries)
```

特点：
- ✅ 所有 Agent 都能看到完整状态
- ✅ 容易做去重、协调
- ❌ 多个 Agent 并发读写时有竞态
- ❌ 状态膨胀后，"读哪一部分"成了新问题
- ❌ 需要锁或 CAS，工程复杂度上升

### 方式 3：文件（File-based）

**Agent 把产出写到磁盘文件，下游 Agent 读取**：

```python
# 文件
def searcher_run(topic):
    findings = do_search(topic)
    Path(f"work/research/{topic}.md").write_text(findings)
    return f"work/research/{topic}.md"  # 只把路径传出去

def writer_run(paths):
    files = [Path(p).read_text() for p in paths]
    return write_report(files)
```

特点：
- ✅ 持久化——worker 跑挂了，已写的文件还在
- ✅ 路径在消息里，但内容按需加载，不会撑爆 context
- ✅ 人也能直接看（调试方便）
- ❌ 文件 I/O 比内存慢（但相对 LLM 调用可忽略）
- ❌ 文件命名、清理需要规范

---

## 二、三种方式的对比

把上面三种摆在一起，按几个维度看清差异：

| 维度 | 消息 | 共享状态 | 文件 |
|------|------|---------|------|
| **传输 token 成本** | 高（全在 context） | 中（读到时才进 context） | 低（路径在 context，内容按需读） |
| **大数据传输** | ✗ 容易爆 | ✗ 读时爆 | ✓ 友好 |
| **持久化** | ✗ | △（看实现） | ✓ 默认有 |
| **并发安全** | ✓（无共享） | ✗（需锁） | △（按文件粒度天然隔离） |
| **调试便利性** | △（看 trace） | ✗（要导出全状态） | ✓（直接看文件） |
| **可恢复性** | ✗ | △ | ✓ |
| **实现复杂度** | 低 | 中 | 低 |
| **适用场景** | 短数据、控制流 | 协调、去重 | 大数据、产物 |

读出几条经验：

1. **消息适合传"控制信号"**：任务、参数、状态码、短摘要。一旦数据超过几 K token，消息就开始扛不住。
2. **共享状态适合"协调"**："哪些 topic 已经被 claim 了"、"全局进度"这种小而频繁读的元数据。它**不适合存大数据**——一旦黑板变大，所有 Agent 都得读它，反而成了新的瓶颈。
3. **文件适合"产出"**：搜来的资料、写好的报告、中间产物。**它和消息其实是互补的——把路径作为消息传，内容存在文件里**。

---

## 三、给 demo 选定一个混合方案

回到 GPU 推理优化调研的 demo，三种方式不是二选一，而是各管一摊：

```
通信方式选择：
- Planner → Searcher：消息（任务参数：topic、key_questions、文件输出路径）
- Searcher → 文件系统：文件（搜来的资料、生成的摘要分两份写）
- Searcher → Planner：消息（只回传"已完成 + 摘要文件路径"）
- Planner → Writer：消息（待整合的摘要文件路径列表）
- Writer → 文件系统：文件（最终报告）
- 全局协调（已 claim 的 topic、并发 worker 数）：共享状态（小内存字典）
```

落到代码层面：

```python
work_dir = Path("./work")  # 工作目录
work_dir.mkdir(exist_ok=True)

shared_state = {
    "claimed_topics": set(),  # 哪些 topic 已经在做
    "completed": {},          # topic → 摘要文件路径
    "errors": {},             # topic → 错误信息
}

def searcher_run(topic, work_dir):
    # 工作过程写文件
    raw_path = work_dir / f"raw/{topic}.md"
    summary_path = work_dir / f"summary/{topic}.md"

    findings = do_search_and_read(topic)
    raw_path.write_text(findings)  # 完整资料留档

    summary = summarize(findings)
    summary_path.write_text(summary)  # 摘要单独存

    # 只传路径回去
    return {"topic": topic, "summary_path": str(summary_path)}


def planner_run(question):
    topics = plan_subtopics(question)

    # 消息分发任务（含输出路径）
    results = parallel_map(
        lambda t: searcher_run(t, work_dir),
        topics
    )

    # 给 Writer 传路径列表
    paths = [r["summary_path"] for r in results]
    return writer_run(question, paths)


def writer_run(question, summary_paths):
    summaries = [Path(p).read_text() for p in summary_paths]
    return write_report(question, summaries)
```

新版本 Searcher 同时做两件事：

1. 把完整资料写到 `work/raw/{topic}.md`（留档）
2. 把摘要写到 `work/summary/{topic}.md`（下游用）

只把路径作为消息传出去。

---

## 四、为什么不全用消息？

读到这里你可能会问：消息最简单啊，为什么不直接全用消息？

确实**早期的多 Agent 框架（CrewAI / AutoGen 早期版本）默认全用消息**。然后大家踩了一遍同样的坑：

### 坑 1：context 一传一倍

Searcher 摘要 5K token，5 个 worker 就 25K。这 25K 全部塞进 Writer 的 context，加上 Writer 自己的 system prompt 和 question，**Writer 启动时 context 已经占了 40K**。再写报告时还要思考、引用、组织，**最终 context 经常突破 80K**。

如果改成"路径 + 按需读"，Writer 启动时 context 只有 < 5K，按需 read 文件，每次只读它当下需要的那一部分。

### 坑 2：长程依赖断链

Writer 写到一半发现需要某篇论文的具体段落。如果前面是消息传的摘要，原文已经丢了——只能让对应 Searcher 重新跑一遍。如果是文件方案，Writer 直接 `read_file("work/raw/FlashAttention.md")` 就拿到了。

### 坑 3：失败不可恢复

5 个 worker 跑了 7 分钟，第 5 个挂了。如果是消息方案，前 4 个的结果还在调用栈里——但调用栈一旦异常退出，结果也就丢了。文件方案下，已完成的 4 份摘要文件还在磁盘上，重跑只需要重新跑第 5 个 worker，**不用从头再来**。

### 坑 4：调试看不到中间过程

消息方案下，Searcher 的工作过程都在它的 LLM 调用栈里。出问题了只能看 trace（如果有 trace 的话）。文件方案下，**直接打开 `work/raw/{topic}.md` 就能看到 Searcher 搜到了什么**——这是巨大的调试便利。

---

## 五、通信的失败模式

引入文件 + 共享状态后，我们也引入了一组新的失败模式。这一节诚实地把它们列出来。

### 失败 1：文件路径冲突

两个 worker 同时写 `work/summary/PagedAttention.md`（一个是 PagedAttention 的 worker，一个是 vLLM 的 worker 顺手做了 PagedAttention 总结）。

**应对**：路径用 worker_id 命名空间隔离，比如 `work/summary/{worker_id}/{topic}.md`。

### 失败 2：共享状态竞态

两个 worker 同时检查 `claimed_topics`，都看到没人 claim PagedAttention，都开始做。

**应对**：claim 操作用锁原子化。Python 的 `threading.Lock` 或者 `asyncio.Lock` 就够。

### 失败 3：文件没写完就被读

Searcher 写到一半，Planner 已经看到 `summary_path` 在共享状态里，让 Writer 开始读——读到了半个文件。

**应对**：原子写——先写到临时文件，写完后 `os.rename` 到目标路径。`rename` 在主流文件系统上是原子的。

### 失败 4：清理不干净

跑一次调研留下几十个文件，下次再跑同名 topic 时混进了上次的内容。

**应对**：每次启动 Planner 时先清空（或者归档到带时间戳的目录）。

### 失败 5：跨机器场景

如果 worker 跑在别的机器上，"文件"就不是本地磁盘了——得用对象存储（S3）或者 NFS。

**应对**：把"文件"抽象成一个 Storage 接口，本地实现读写本地磁盘，分布式实现读写 S3。Demo 暂时只做本地。

---

## 六、第二版骨架（含文件通信）的执行图

把第二版的执行流程画出来：

```
┌────────────┐
│  Planner   │
└─────┬──────┘
      │ 消息：{topic, output_paths}
      ▼
┌────────────────────────────────┐
│ Searcher × 5 (parallel)        │
│   ↓ 写文件                      │
│ ┌─────────────────────────┐    │
│ │ work/raw/{topic}.md     │    │
│ │ work/summary/{topic}.md │    │
│ └─────────────────────────┘    │
└─────┬──────────────────────────┘
      │ 消息：{topic, summary_path}
      ▼
┌────────────┐
│  Planner   │ (聚合所有 summary_path)
└─────┬──────┘
      │ 消息：{summary_paths: [...]}
      ▼
┌────────────┐
│   Writer   │
│   ↓ 按需读  │
│   ↓ 写报告  │
└─────┬──────┘
      │
      ▼
   work/report.md
```

注意几个细节：

- **任务和摘要是分开的两次消息**——发任务时只传输入（topic）；返回时只传产出路径
- **完整资料和摘要分两个文件**——下游一般只读摘要，需要时再深入读原文
- **Planner 自己不读文件**——它只做调度，避免它的 context 被资料污染

---

## 一句话总结

多 Agent 的通信不是"消息 vs 共享状态 vs 文件"三选一，而是**三件事各管一摊**：

- **消息**传控制信号（任务、状态、路径）
- **文件**传产出（资料、摘要、报告）
- **共享状态**做协调（已 claim、全局进度）

最常见的反模式是"全用消息"——简单直觉，但会让 context 爆炸、失败不可恢复、调试看不到过程。一旦你的多 Agent 系统有 worker 产出超过 5K token 的内容，**就该把这部分内容搬到文件里**。

---

## 下一篇预告

这一章我们解决了"用什么传话"——但还没解决"怎么把消息接力起来"。

第二版的执行图本质上是一个固定的 DAG：Planner 拆任务 → 5 个 Searcher 并行 → Planner 聚合 → Writer 整合。这是**Workflow** 模式。

但还有别的模式。比如让 Planner 一直当"老板"，Searcher 完成后回报给它，由它决定要不要再派新任务、要不要终止——这是 **Supervisor** 模式。或者完全去中心化，Agent 之间互相调用、自主路由——这是 **Swarm** 模式。

下一章我们用三种模式各重写一遍 demo，看哪种最适合调研场景，**剧透：Swarm 看起来最 AI，但生产环境几乎没人用**。

---

*这一章的核心代码新增 ~50 行（文件 I/O + 共享状态），累计 ~250 行。*
