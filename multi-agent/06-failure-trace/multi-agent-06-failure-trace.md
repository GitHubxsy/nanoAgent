# 从零开始做 Multi-Agent 系统（六）：错误传播、重试与可观测性

> **「从零开始做 Multi-Agent 系统」系列** —— 第六篇。前五章 demo 已经能稳定跑出高质量报告——大部分时候。但 1/5 的运行会以某种形式崩溃。这一章处理多 Agent 系统真正难的部分：失败模式、重试、critic、可观测性。
>
> - [第一篇：什么时候单 Agent 不够](../01-when-single-agent-fails/)
> - [第二篇：最小多 Agent 骨架](../02-minimum-skeleton/)
> - [第三篇：Agent 之间怎么传话](../03-communication/)
> - [第四篇：编排模式之争](../04-orchestration/)
> - [第五篇：状态、记忆与上下文](../05-state-memory/)
> - **第六篇：错误传播、重试与可观测性**（本文）
> - 第七篇：边界与反模式（即将更新）

---

## 开场：1/5 的概率，demo 会以某种诡异方式崩

跑 20 次第五章版本的 demo，能跑出"完整 + 多角度报告"的概率大概是 16 次。剩下 4 次以下面的某种方式崩：

**崩法 1（最常见）**：某个 Searcher 卡了 8 分钟没返回。Python 的 ThreadPoolExecutor 没设超时，主线程一直等。

**崩法 2**：模型给 Planner 的拆任务 JSON 格式不对——多了一个尾随逗号、字符串里有未转义引号、整段不是合法 JSON。`json.loads` 抛异常，整个调研废了。

**崩法 3**：Searcher 跑了 6 分钟后 LLM API 返回 429（限流）。原本可能只是"等一会重试就好"的小问题，但代码没做重试，这个 worker 直接抛异常退出。

**崩法 4（最隐蔽）**：所有 worker 都正常返回，报告也写出来了——**但内容大量是错的**。模型在调研时被一个写得很自信的过时博客带偏了，整篇报告引用的都是 2023 年的数据，没有任何机制告诉你"这份报告不靠谱"。

前三种是显式失败，最后一种是**隐式失败**——也是最危险的一种。

这一章把这两类都解掉。

---

## 一、多 Agent 系统的失败模式分类

把可能的失败摆出来分类，比模糊地说"加重试"有用。

### 类型 A：传输层失败

发生在 Agent 之间或者 Agent 和外部世界之间的 I/O 环节。

- API 限流（429）
- API 超时
- 网络错误
- 文件 I/O 错误

特征：**通常是临时的**。重试就好。

### 类型 B：协议层失败

Agent 输出格式不对，下游解析不出来。

- JSON 不合法
- 缺必需字段
- 类型错（应该是 list，给了 string）

特征：**模型相关的偶发**。重试 + 加严格 schema 校验 + 给模型反馈错误信息让它重试。

### 类型 C：执行层失败

Agent 自己的逻辑跑挂了。

- Worker 进入死循环
- 步数超过预设上限
- 返回的数据为空

特征：**通常意味着任务本身有问题**。需要"放弃 + 报告"，不能傻傻重试。

### 类型 D：质量层失败（隐式）

Agent 全部正常完成，但**结果不对**。

- 信息过时
- 幻觉（编造的论文 / URL）
- 视角片面

特征：**程序无法直接检测**。需要 critic Agent 主动质疑。

---

## 二、应对类型 A、B、C：重试策略矩阵

针对前三类显式失败，写一套分级的重试策略。

```python
# retry.py
import time
import random
from dataclasses import dataclass

@dataclass
class RetrySpec:
    max_attempts: int
    backoff_base: float       # 指数退避起步
    backoff_cap: float        # 退避上限
    on: tuple                 # 哪些异常触发重试

# 按失败类型配不同策略
RETRY_POLICIES = {
    # 传输层：积极重试
    "api_call": RetrySpec(
        max_attempts=5,
        backoff_base=2.0,
        backoff_cap=60.0,
        on=(RateLimitError, TimeoutError, ConnectionError),
    ),

    # 协议层：少量重试，每次把错误反馈给模型
    "llm_json_output": RetrySpec(
        max_attempts=3,
        backoff_base=0.5,
        backoff_cap=2.0,
        on=(json.JSONDecodeError, SchemaValidationError),
    ),

    # 执行层：极少重试或不重试
    "worker_run": RetrySpec(
        max_attempts=2,
        backoff_base=0,
        backoff_cap=0,
        on=(WorkerStuckError,),
    ),
}


def with_retry(spec_name: str, fn, *args, **kwargs):
    spec = RETRY_POLICIES[spec_name]
    last_err = None
    for attempt in range(spec.max_attempts):
        try:
            return fn(*args, **kwargs)
        except spec.on as e:
            last_err = e
            if attempt + 1 < spec.max_attempts:
                wait = min(spec.backoff_base ** attempt, spec.backoff_cap)
                wait += random.random() * 0.5  # 加 jitter
                time.sleep(wait)
    raise last_err
```

调用方：

```python
# API 调用包一层
result = with_retry("api_call", web_read, url)

# LLM JSON 输出包一层（连同"把错误反馈给模型"）
def llm_json_call(prompt, schema):
    last_err = None
    for attempt in range(3):
        try:
            output = llm_call(prompt)
            return parse_and_validate(output, schema)
        except SchemaValidationError as e:
            last_err = e
            # 把错误信息反馈回模型
            prompt = prompt + f"\n\n(上次输出格式不对：{e}。请严格按 schema 重输)"
    raise last_err
```

### Worker 失败的两种应对：失败重试 vs 放弃 + 标记

到 worker 层面，重试要更克制。`parallel_map` 改成"全部并行 + 单个失败不影响其他"：

```python
def parallel_map_with_isolation(fn, items, scratchpad):
    """每个任务独立 try-except，失败的标记到 scratchpad，不阻塞其他。"""
    futures = {executor.submit(fn, item): item for item in items}
    results = {}
    for fut in as_completed(futures):
        item = futures[fut]
        try:
            results[item] = fut.result(timeout=600)  # 10 分钟硬上限
        except Exception as e:
            scratchpad.record_error(item, e)
            results[item] = None
    return results
```

跑下来，5 个 Searcher 中 1 个挂了，剩下 4 个的结果都还在。Writer 收到的是 "4 个完整摘要 + 1 个错误标记"，能选择：

- 报告里写 "TensorRT-LLM 的调研因技术问题未完成，建议读者手动查询"
- 或者：用剩下 4 个写一份完整的，最后加个 caveat

---

## 三、应对类型 D：critic Agent

显式失败靠重试，**隐式失败靠 critic**。

Critic 的核心思想是：**让一个独立的、不知道"前面发生了什么"的 Agent 来质疑结果**。它没读过 worker 读的资料，没有"我已经投入了 5 分钟"的沉没成本，因此能更冷静地挑毛病。

### Critic 的输入与输出

```python
class Critic:
    def critique(self, report: str, scratchpad_snapshot: dict) -> dict:
        prompt = f"""
你是一个严苛的技术审稿人。下面是一份调研报告和它的依据。
你的任务是找出这份报告的问题，包括但不限于：

1. 信息时效性：是否引用了过时数据？
2. 信息可信度：来源是否权威？是否有立场偏差？
3. 逻辑漏洞：结论是否真的能从依据推出？
4. 视角片面：是否只展示了某一方观点？
5. 关键缺失：有没有重要方案/角度被漏掉？

请给出 issues 列表，每个 issue 标明严重等级（critical / major / minor）。
如果有 critical 或 major issue，建议处理方案。

报告：
{report}

依据（key findings）：
{json.dumps(scratchpad_snapshot["key_findings"], indent=2)}

冲突标记：
{json.dumps(scratchpad_snapshot["conflicts"], indent=2)}
"""
        result = llm_call(prompt)
        return parse_critique(result)
```

### Critic 的位置

Critic 应该放在哪一阶段？三个选项：

1. **Worker 之后、Writer 之前**：批判每个 Searcher 的摘要
2. **Writer 之后、返回之前**：批判最终报告
3. **两个都有**

经验：**默认放 #2，必要时再加 #1**。

为什么？因为 #1 会让 Critic 的工作量随 worker 数量线性增长（5 个 worker 就要批判 5 次），而 #2 只批判 1 次最终产物。一次批判最终报告，能覆盖大部分 worker 阶段的问题——除非某个 worker 的输出质量极差，那 Writer 整合时就会出问题，#2 也能查出来。

### Critic 触发的修正循环

Critic 找到 critical issue 时，触发一次修正：

```python
def hybrid_run_with_critic(question: str) -> str:
    scratchpad = Scratchpad(...)
    topics = planner_node(question)
    summary_paths = parallel_map_with_isolation(
        lambda t: supervised_search(t, scratchpad),
        topics, scratchpad
    )

    report = writer_node(question, summary_paths, scratchpad.snapshot_for_writer())

    # === 新增：critic 循环 ===
    for round_idx in range(2):  # 最多 2 轮修正
        critique = Critic().critique(report, scratchpad.snapshot_for_writer())

        if not has_critical_issues(critique):
            break

        # 把 critic 反馈给 Writer，让它修正
        report = writer_node_with_critique(
            question, summary_paths, scratchpad.snapshot_for_writer(),
            previous_report=report,
            critique=critique,
        )

    return report
```

注意 `for round_idx in range(2)` 这个上限——**一定要给 critic 循环加上限**。否则会出现 critic 永远不满意、Writer 永远在改的死循环。

---

## 四、可观测性：trace 是多 Agent 系统的命根子

加完 retry 和 critic 后，demo 的成功率从 80% 提升到 95%+。剩下的 5% 还是会失败——但你怎么知道是哪里失败了？

**多 Agent 系统不可观测就约等于不可用**。

### Trace 应该记什么

我们设计一个最小可用的 trace 模块：

```python
# trace.py
import time
import json
import uuid
from contextvars import ContextVar
from pathlib import Path

current_trace_id = ContextVar("trace_id", default=None)

class TraceLogger:
    def __init__(self, path: Path):
        self.path = path
        self.events = []

    def log(self, event_type: str, **kwargs):
        self.events.append({
            "ts": time.time(),
            "trace_id": current_trace_id.get(),
            "event": event_type,
            **kwargs,
        })

    def flush(self):
        self.path.write_text(
            "\n".join(json.dumps(e) for e in self.events)
        )

trace = TraceLogger(work_dir / "trace.jsonl")


# Agent 装饰器：自动记录入参 + 出参 + 耗时
def traced(agent_name: str):
    def decorator(fn):
        def wrapper(*args, **kwargs):
            tid = str(uuid.uuid4())[:8]
            current_trace_id.set(tid)
            t0 = time.time()
            trace.log("agent_start", agent=agent_name, args=str(args)[:500])
            try:
                result = fn(*args, **kwargs)
                trace.log("agent_end", agent=agent_name,
                         duration=time.time() - t0,
                         result_summary=str(result)[:500])
                return result
            except Exception as e:
                trace.log("agent_error", agent=agent_name,
                         duration=time.time() - t0,
                         error=str(e))
                raise
        return wrapper
    return decorator


# 用法
@traced("Searcher")
def searcher_run(topic):
    ...

@traced("LLMCall")
def llm_call(prompt):
    trace.log("llm_input", tokens=count_tokens(prompt))
    response = client.complete(prompt)
    trace.log("llm_output", tokens=count_tokens(response))
    return response
```

输出的 trace 文件长这样（每行一个 JSON 事件）：

```json
{"ts": 1731.0, "event": "agent_start", "agent": "Planner", "args": "调研 GPU 推理优化"}
{"ts": 1731.5, "event": "llm_input", "tokens": 1245}
{"ts": 1734.2, "event": "llm_output", "tokens": 487}
{"ts": 1734.3, "event": "agent_end", "agent": "Planner", "duration": 3.3, "result_summary": "[\"FlashAttention\", ...]"}
{"ts": 1734.5, "event": "agent_start", "agent": "Searcher", "args": "FlashAttention", ...}
...
```

### 用 trace 反推失败原因

跑了一次失败的 demo，打开 trace 文件 grep 一下：

```bash
# 找出所有 error 事件
grep '"event": "agent_error"' work/trace.jsonl

# 找出耗时超过 60s 的 agent 调用
jq 'select(.event == "agent_end" and .duration > 60)' work/trace.jsonl

# 统计每个 agent 的总 token 消耗
jq 'select(.event == "llm_output") | {agent: .agent, tokens: .tokens}' work/trace.jsonl
```

5 分钟以内你就能看清：

- 哪一步卡了
- 哪个 worker 的 LLM 调用最贵
- error 是发生在哪里、当时上下文是什么

### Trace 可视化

文本 trace 已经够用了，但配一个可视化能让你眼前一亮。简单做法是把 trace 渲染成时间线：

```python
def render_trace_html(trace_path: Path) -> str:
    events = [json.loads(l) for l in trace_path.read_text().splitlines()]
    # 按 agent 分组，画甘特图
    ...
```

每个 Agent 一行、横轴是时间、彩色块是 LLM 调用。一眼能看出哪个并行 worker 拖了后腿、哪个 agent 重复调用了 LLM。

---

## 五、用 trace 反推：哪个 worker 在装睡，哪个 critic 在敷衍

trace 的真正威力不是排查崩溃——是**发现"看起来正常但其实不对"的问题**。

### 案例 1：装睡的 Searcher

跑了一周后，统计 trace 数据：

```
Searcher_FlashAttention   平均 LLM 调用：12 次  平均 web_read：8 次   摘要长度：~1200 字
Searcher_PagedAttention   平均 LLM 调用：14 次  平均 web_read：9 次   摘要长度：~1400 字
Searcher_TensorRT-LLM     平均 LLM 调用：4 次   平均 web_read：2 次   摘要长度：~300 字  ← 异常
Searcher_SGLang           平均 LLM 调用：11 次  平均 web_read：7 次   摘要长度：~1100 字
Searcher_vLLM             平均 LLM 调用：13 次  平均 web_read：8 次   摘要长度：~1300 字
```

`Searcher_TensorRT-LLM` 明显在装睡——它调用次数和摘要长度都不到别人 1/3。**没有 trace 你永远不会发现这个问题**——它每次都"正常返回"，只是返回得太草率。

排查后发现：TensorRT-LLM 的官方文档需要登录才能完整访问，web_read 抓不到核心内容，Searcher 提前放弃了。

### 案例 2：敷衍的 Critic

trace 显示 Critic 平均每次调用消耗 ~3K tokens，但 90% 的输出都是"未发现重大问题"。

**Critic 在敷衍**——它没真的批判，只是套了模板。

排查后发现：Critic 的 prompt 里没强制要求"必须挑出至少 2 个 issues 才能通过"，模型默认走"积极反馈"模式。改 prompt 加上"宁可挑过头也不要漏掉"后，Critic 才真的开始干活。

---

这两个案例的共同点是：**问题发生时一切看起来都正常**。没有 trace，你只会觉得"咦，最近报告怎么又出了几次问题"，但找不到原因。有 trace，5 分钟就能锁定。

---

## 一句话总结

多 Agent 系统的成功率不是各 Agent 成功率相乘那么简单——**错误会累积放大**。

应对策略要分层：

- **传输层**：积极重试 + 退避 + jitter
- **协议层**：少量重试 + 反馈错误给模型
- **执行层**：硬上限 + 失败标记 + 不阻塞其他 worker
- **质量层**：critic Agent 主动质疑 + 修正循环（带轮数上限）

**Trace 是多 Agent 系统的命根子**——加它的成本不到半天，但少了它，5% 的失败率永远查不到原因，"装睡的 worker"和"敷衍的 critic"也永远发现不了。

---

## 下一篇预告

到这一章结束，我们的多 Agent 系统已经是个能用的产品级雏形——稳定率 95%+、有 critic、有 trace、有错误处理、有共享状态。

但接下来要面对一个更难的问题：**它真的值吗？**

第七章是一次回头算账——把六章累计下来的 token、耗时、代码量摆出来，对比第一章那个简陋的单 Agent baseline。看看哪些章节是真的赢了，哪些其实是"沟通税"。然后给出反模式清单：什么情况下你应该退回单 Agent + SubAgent 的折中方案，而不是搞一套完整的多 Agent 团队。

这是收尾章，也是这个系列最重要的一章——所有"为多 Agent 而多 Agent"的批评，都会在这一章正面回应。

---

*这一章新增 ~200 行代码（retry + critic + trace + 可视化），累计 ~570 行。*
