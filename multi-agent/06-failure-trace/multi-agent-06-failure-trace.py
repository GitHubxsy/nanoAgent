"""
Multi-Agent 系列（六）：错误传播、重试与可观测性

第六版：在第五版基础上加：
- 分级 retry（API / JSON / Worker 三档）
- Critic Agent（最终报告后批判 + 触发修正循环，max 2 轮）
- TraceLogger（JSONL 格式，记录所有 agent / llm / tool 事件）
- parallel_map_with_isolation（单个 worker 失败不影响其他）

跑：
    OPENAI_API_KEY=... python multi-agent-06-failure-trace.py
然后看 work/trace.jsonl
"""

import os
import json
import time
import random
import uuid
import threading
import functools
import httpx
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed
from openai import OpenAI

client = OpenAI(
    api_key=os.environ.get("OPENAI_API_KEY"),
    base_url=os.environ.get("OPENAI_BASE_URL"),
    http_client=httpx.Client(verify=False),
)
MODEL = os.environ.get("OPENAI_MODEL", "gpt-4o-mini")

WORK = Path("./work"); WORK.mkdir(exist_ok=True)


# ============ Trace ============
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
            self.path.write_text("\n".join(json.dumps(e, ensure_ascii=False) for e in self.events))


trace = TraceLogger(WORK / "trace.jsonl")


def traced(name: str):
    """装饰器：自动记录 agent 调用入参 / 出参 / 耗时 / 错误。"""
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


# ============ Retry ============
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


# ============ Mock 工具 + 注入故障 ============
MOCK_PAGES = {
    "https://example.com/fa3": "FlashAttention-3 比 v2 快 1.5x" * 30,
    "https://example.com/pa-v2": "PagedAttention v2 比 FA 快 1.8x" * 30,
    "https://example.com/sglang": "SGLang RadixAttention" * 25,
    "https://example.com/vllm": "vLLM 高吞吐" * 25,
    "https://example.com/trtllm": "TRT-LLM NVIDIA 优化" * 25,
}
MOCK_SEARCH = {k: [{"title": k, "url": f"https://example.com/{k.lower()[:8]}", "snippet": k}]
               for k in ["FlashAttention", "PagedAttention", "SGLang", "vLLM", "TensorRT-LLM"]}
MOCK_SEARCH["FlashAttention"][0]["url"] = "https://example.com/fa3"
MOCK_SEARCH["PagedAttention"][0]["url"] = "https://example.com/pa-v2"


@with_retry(max_attempts=3, backoff=0.5)
def web_search(q):
    # 5% 概率注入瞬时失败，演示 retry
    if random.random() < 0.05:
        raise httpx.ConnectError("simulated network blip")
    time.sleep(0.2)
    for k, r in MOCK_SEARCH.items():
        if k.lower() in q.lower():
            return json.dumps(r, ensure_ascii=False)
    return "[]"


@with_retry(max_attempts=3, backoff=1.0)
def web_read(url):
    if random.random() < 0.05:
        raise TimeoutError("simulated timeout")
    time.sleep(0.5)
    return MOCK_PAGES.get(url, "(not found)")[:5000]


def llm(messages, tools=None):
    resp = client.chat.completions.create(model=MODEL, messages=messages, tools=tools)
    if resp.usage:
        trace.log("llm_call", in_tokens=resp.usage.prompt_tokens, out_tokens=resp.usage.completion_tokens)
    return resp.choices[0].message


SEARCH_TOOLS = [
    {"type": "function", "function": {"name": "web_search",
        "parameters": {"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]}}},
    {"type": "function", "function": {"name": "web_read",
        "parameters": {"type": "object", "properties": {"url": {"type": "string"}}, "required": ["url"]}}},
]


# ============ Agents ============
@traced("Planner")
def planner(q):
    m = llm([
        {"role": "system", "content": "把问题拆成 3-8 独立子主题。返回 JSON 数组。"},
        {"role": "user", "content": q},
    ])
    t = m.content or ""
    s, e = t.find("["), t.rfind("]")
    return json.loads(t[s:e+1]) if s >= 0 < e else []


@traced("Searcher")
def searcher(topic):
    messages = [
        {"role": "system", "content": f"调研「{topic}」。最后写 300 字摘要。"},
        {"role": "user", "content": f"调研 {topic}"},
    ]
    for _ in range(8):
        msg = llm(messages, tools=SEARCH_TOOLS)
        messages.append(msg)
        if not msg.tool_calls:
            return msg.content or ""
        for tc in msg.tool_calls:
            args = json.loads(tc.function.arguments)
            fn = {"web_search": web_search, "web_read": web_read}[tc.function.name]
            try:
                result = fn(**args)
            except Exception as e:
                result = f"Error after retries: {e}"
            messages.append({"role": "tool", "tool_call_id": tc.id, "content": result[:4000]})
    return "(超过迭代上限)"


@traced("Critic")
def critic(report):
    msg = llm([
        {"role": "system", "content": "你是严苛的审稿人。找出报告的 issues：时效性、可信度、逻辑、视角、关键缺失。"
                                       "返回 JSON：[{severity: critical|major|minor, issue, suggestion}]。"
                                       "宁可挑过头也不要漏。"},
        {"role": "user", "content": report},
    ])
    text = msg.content or ""
    s, e = text.find("["), text.rfind("]")
    try:
        return json.loads(text[s:e+1]) if s >= 0 < e else []
    except Exception:
        return []


@traced("Writer")
def writer(q, summaries, critique=None, prev_report=None):
    digest = "\n\n".join(f"### {t}\n{s}" for t, s in summaries.items())
    extra = ""
    if critique and prev_report:
        extra = (f"\n\n上一版报告：\n{prev_report}\n\nCritic 反馈：\n"
                 + json.dumps(critique, ensure_ascii=False, indent=2)
                 + "\n请针对 critical / major issues 修正。")
    msg = llm([
        {"role": "system", "content": "基于摘要写对比报告（~1500 字）。"},
        {"role": "user", "content": f"问题：{q}\n摘要：\n{digest}{extra}"},
    ])
    return msg.content or ""


def parallel_map_with_isolation(fn, items, max_workers=None):
    """单个 task 失败不影响其他，超时 600s。"""
    results = {}
    errors = {}
    with ThreadPoolExecutor(max_workers=max_workers or len(items)) as pool:
        futs = {pool.submit(fn, x): x for x in items}
        for f in as_completed(futs):
            x = futs[f]
            try:
                results[x] = f.result(timeout=600)
            except Exception as e:
                errors[x] = str(e)
                trace.log("worker_failed", task=str(x), error=str(e))
    return results, errors


# ============ 主流程 ============
def run(q, max_critic_rounds=2):
    trace.log("run_start", question=q)
    t_total = time.time()

    topics = planner(q)
    print(f"[Planner] {topics}")

    print(f"[Searchers] 并行 {len(topics)}（带隔离）")
    summaries, errors = parallel_map_with_isolation(searcher, topics)
    print(f"  ✓ 成功 {len(summaries)}, 失败 {len(errors)}")
    if errors:
        print(f"  失败列表：{errors}")

    report = writer(q, summaries)

    for rnd in range(max_critic_rounds):
        print(f"[Critic round {rnd+1}]")
        issues = critic(report)
        critical = [i for i in issues if i.get("severity") in ("critical", "major")]
        print(f"  发现 issues: {len(issues)} (critical/major: {len(critical)})")
        if not critical:
            break
        report = writer(q, summaries, critique=issues, prev_report=report)

    out = WORK / "report-multi-v6.md"
    out.write_text(report)
    trace.log("run_end", duration=round(time.time() - t_total, 2))
    trace.flush()
    print(f"\n[Done] 报告：{out}")
    print(f"[Trace] 写到 {trace.path}（grep / jq 查看）")
    return report


if __name__ == "__main__":
    q = "对比 FlashAttention / PagedAttention / SGLang / vLLM / TensorRT-LLM 长上下文场景"
    print(f"=== 第六版：Retry + Critic + Trace ===\n{q}\n")
    run(q)
