# 从零开始做 Multi-Agent 系统（六）：错误传播、重试与可观测性

> **「从零开始做 Multi-Agent 系统」系列** —— 第六篇。前五章 demo 已经能稳定跑出高质量报告——大部分时候。但 1/5 的运行会以某种形式崩溃。这一章处理多 Agent 系统真正难的部分：失败模式、重试、critic、可观测性。
>
> - [第一篇：什么时候单 Agent 不够](../01-when-single-agent-fails/multi-agent-01-when-single-agent-fails.md)
> - [第二篇：最小多 Agent 骨架](../02-minimum-skeleton/multi-agent-02-minimum-skeleton.md)
> - [第三篇：Agent 之间怎么传话](../03-communication/multi-agent-03-communication.md)
> - [第四篇：编排模式之争](../04-orchestration/multi-agent-04-orchestration.md)
> - [第五篇：状态、记忆与上下文](../05-state-memory/multi-agent-05-state-memory.md)
> - **第六篇：错误传播、重试与可观测性**（本文）
> - [第七篇：边界与反模式](../07-boundaries/multi-agent-07-boundaries.md)

---

## 一、先说结论

| 失败类型 | 例子 | 应对策略 |
|---------|------|---------|
| 传输层（A） | API 限流、超时、网络断 | 积极重试 + 指数退避 + jitter |
| 协议层（B） | JSON 格式不对、缺必需字段 | 少量重试 + 把错误反馈给模型 |
| 执行层（C） | Worker 死循环、步数超限 | 硬上限 + 放弃标记 + 不阻塞其他 |
| 质量层（D） | 信息过时、幻觉、视角片面 | Critic Agent 主动质疑 + 修正循环 |

一句话总结：**显式失败靠重试，隐式失败靠 Critic，所有失败靠 Trace 找根因**。多 Agent 系统的错误会累积放大——5 个 Agent 各 95% 成功率，串起来只有 77%。不分层处理，成功率上不去。

---

## 二、开场：1/5 的概率崩

跑 20 次第五章版本的 demo，能跑出完整报告的大概 16 次。剩下 4 次以下面的某种方式崩：

| 崩法 | 表现 | 类型 |
|------|------|------|
| Searcher 卡 8 分钟 | ThreadPoolExecutor 没设超时，主线程一直等 | 执行层 |
| Planner 的 JSON 不对 | 尾随逗号、未转义引号，`json.loads` 抛异常 | 协议层 |
| API 返回 429 | 限流了，代码没做重试，worker 直接退出 | 传输层 |
| 报告内容大量错误 | 被过时博客带偏，全篇引用 2023 年数据 | 质量层 |

前三种是显式失败——程序崩了你知道。最后一种是**隐式失败**——程序跑完了，但结果不对，**最危险**。

---

## 三、应对显式失败：分级重试

### 3.1 重试策略

配套代码在 [multi-agent-06-failure-trace.py](./multi-agent-06-failure-trace.py)，核心是 `with_retry` 装饰器：

```python
def with_retry(max_attempts=3, backoff=0.5, on=(Exception,)):
    def deco(fn):
        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            last = None
            for attempt in range(max_attempts):
                try:
                    return fn(*args, **kwargs)
                except on as e:
                    last = e
                    trace.log("retry", fn=fn.__name__, attempt=attempt, err=str(e))
                    if attempt + 1 < max_attempts:
                        time.sleep(backoff * (2 ** attempt) + random.random() * 0.3)
            raise last
        return wrapper
    return deco
```

按失败类型配不同参数：

| 层级 | max_attempts | backoff | 策略 |
|------|-------------|---------|------|
| 传输层（API 调用） | 3-5 | 0.5-2s | 积极重试，加 jitter 防雪崩 |
| 协议层（JSON 解析） | 2-3 | 0.5s | 把错误反馈给模型让它重输 |
| 执行层（Worker） | 1-2 | 0 | 极少重试，更多靠"放弃 + 标记" |

### 3.2 Worker 失败隔离

`parallel_map` 改成"单个失败不阻塞其他"：

```python
def parallel_map_with_isolation(fn, items, max_workers=None):
    results = {}
    errors = {}
    with ThreadPoolExecutor(max_workers=max_workers or len(items)) as pool:
        futs = {pool.submit(fn, x): x for x in items}
        for f in as_completed(futs):
            x = futs[f]
            try:
                results[x] = f.result(timeout=600)  # 10 分钟硬上限
            except Exception as e:
                errors[x] = str(e)
                trace.log("worker_failed", task=str(x), error=str(e))
    return results, errors
```

5 个 Searcher 中 1 个挂了，剩下 4 个的结果都还在。Writer 收到的是"4 个完整摘要 + 1 个错误标记"，能在报告里注明缺失。

---

## 四、应对隐式失败：Critic Agent

显式失败靠重试，**隐式失败靠 Critic**。

### 4.1 Critic 的核心思想

让一个独立的、不知道"前面发生了什么"的 Agent 来质疑结果。它没读过 worker 读的资料，没有沉没成本，因此能更冷静地挑毛病。

```python
@traced("Critic")
def critic(report):
    msg = llm([
        {"role": "system", "content": "你是严苛的审稿人。找出报告的 issues："
                                       "时效性、可信度、逻辑、视角、关键缺失。"
                                       "返回 JSON：[{severity: critical|major|minor, "
                                       "issue, suggestion}]。宁可挑过头也不要漏。"},
        {"role": "user", "content": report},
    ])
    text = msg.content or ""
    s, e = text.find("["), text.rfind("]")
    try:
        return json.loads(text[s:e+1]) if s >= 0 < e else []
    except Exception:
        return []
```

> **关键洞察**：Critic 的 prompt 里**必须强制"宁可挑过头"**。否则模型默认走"积极反馈"模式，90% 的输出是"未发现重大问题"——Critic 在敷衍。

### 4.2 Critic 放在哪

| 位置 | 优势 | 代价 |
|------|------|------|
| Worker 之后、Writer 之前 | 能批判每个摘要 | 工作量随 worker 数线性增长 |
| **Writer 之后、返回之前** | **只批判 1 次最终产物** | **默认选这个** |
| 两者都有 | 最全面 | 最贵 |

经验：**默认放 Writer 之后**。一次批判最终报告，能覆盖大部分 worker 阶段的问题。

### 4.3 修正循环

Critic 找到 critical/major issue 时触发修正，但**一定要加轮数上限**：

```python
def run(q, max_critic_rounds=2):
    topics = planner(q)
    summaries, errors = parallel_map_with_isolation(searcher, topics)

    report = writer(q, summaries)

    for rnd in range(max_critic_rounds):  # 最多 2 轮
        issues = critic(report)
        critical = [i for i in issues if i.get("severity") in ("critical", "major")]
        if not critical:
            break
        report = writer(q, summaries, critique=issues, prev_report=report)

    return report
```

不加上限会出现 Critic 永远不满意、Writer 永远在改的死循环。

---

## 五、可观测性：Trace 是多 Agent 系统的命根子

加完 retry 和 critic 后，成功率从 80% 提升到 95%+。剩下的 5% 还是会失败——但你怎么知道是哪里失败了？

**多 Agent 系统不可观测就约等于不可用。**

### 5.1 TraceLogger 实现

```python
class TraceLogger:
    def __init__(self, path: Path):
        self.path = path
        self.events = []
        self._lock = threading.Lock()

    def log(self, event: str, **kwargs):
        with self._lock:
            self.events.append({"ts": time.time(), "event": event, **kwargs})

    def flush(self):
        with self._lock:
            self.path.write_text("\n".join(
                json.dumps(e, ensure_ascii=False) for e in self.events))
```

配合 `@traced` 装饰器自动记录每个 Agent 的入参、出参、耗时、错误：

```python
def traced(name: str):
    def deco(fn):
        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            tid = str(uuid.uuid4())[:8]
            t0 = time.time()
            trace.log("agent_start", agent=name, trace_id=tid)
            try:
                result = fn(*args, **kwargs)
                trace.log("agent_end", agent=name, trace_id=tid,
                         duration=round(time.time() - t0, 2),
                         result_summary=str(result)[:200])
                return result
            except Exception as e:
                trace.log("agent_error", agent=name, trace_id=tid,
                         duration=round(time.time() - t0, 2), error=str(e))
                raise
        return wrapper
    return deco
```

### 5.2 跑起来

```bash
OPENAI_API_KEY=... python multi-agent-06-failure-trace.py
```

运行后查看 trace：

```bash
# 找出所有 error 事件
grep '"event": "agent_error"' work/trace.jsonl

# 找出耗时超过 60s 的调用
jq 'select(.event == "agent_end" and .duration > 60)' work/trace.jsonl

# 统计 token 消耗
jq 'select(.event == "llm_call")' work/trace.jsonl
```

### 5.3 用 Trace 发现隐蔽问题

Trace 的真正威力不是排查崩溃——是**发现"看起来正常但其实不对"的问题**。

**案例 1：装睡的 Searcher**

统计 trace 数据发现 `Searcher_TensorRT-LLM` 的 LLM 调用次数和摘要长度都不到别人 1/3。它每次都"正常返回"，只是返回得太草率——排查后发现目标文档需要登录才能完整访问，Searcher 提前放弃了。**没有 trace 你永远不会发现这个问题。**

**案例 2：敷衍的 Critic**

Trace 显示 Critic 90% 的输出都是"未发现重大问题"，平均消耗仅 ~3K tokens。Critic 在套模板——改 prompt 加上"宁可挑过头也不要漏掉"后才真的开始干活。

这两个案例的共同点：**问题发生时一切看起来都正常**。没有 trace，你只会觉得"最近报告怎么又出了几次问题"，但找不到原因。有 trace，5 分钟就能锁定。

---

## 六、加完这一章后的对比

| 指标 | 第五章末 | 第六章末（+ Retry + Critic + Trace） |
|------|---------|-------------------------------------|
| 成功率 | ~80% | 95%+ |
| API 瞬时失败处理 | 直接崩 | 自动重试 |
| 单 Worker 崩溃 | 全部废 | 只丢失 1 个，其余正常 |
| 报告质量问题 | 无人察觉 | Critic 主动挑问题 |
| 调试手段 | 肉眼看日志 | Trace + jq 查询 |

---

## 一句话总结

多 Agent 系统的成功率不是各 Agent 成功率相乘那么简单——**错误会累积放大**。应对策略分四层：传输层积极重试，协议层反馈给模型重试，执行层硬上限 + 失败隔离，质量层 Critic 主动质疑。**Trace 是多 Agent 系统的命根子**——加它的成本不到半天，但少了它，"装睡的 worker"和"敷衍的 critic"永远发现不了。

---

## 下一篇预告

到这一章结束，我们的多 Agent 系统已经是个能用的产品级雏形——稳定率 95%+、有 critic、有 trace、有错误处理、有共享状态。

但接下来要面对一个更难的问题：**它真的值吗？**

[第七章](../07-boundaries/multi-agent-07-boundaries.md)是一次回头算账——把六章累计下来的 token、耗时、代码量摆出来，对比第一章那个简陋的单 Agent baseline。看看哪些章节是真的赢了，哪些其实是"沟通税"。然后给出反模式清单：什么情况下你应该退回单 Agent，而不是搞一套完整的多 Agent 团队。

---

*配套代码 [multi-agent-06-failure-trace.py](./multi-agent-06-failure-trace.py) 新增 retry + critic + trace，约 270 行。*
