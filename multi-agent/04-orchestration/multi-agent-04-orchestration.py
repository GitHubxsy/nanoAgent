"""
Multi-Agent 系列（四）：编排模式之争——Workflow / Supervisor / Swarm

本脚本实现三种编排模式各跑一遍同一个 demo，最后选定混合方案
（外层 Workflow + 每个 topic 内部小 Supervisor）作为后续章节的主线。

跑：
    OPENAI_API_KEY=... python multi-agent-04-orchestration.py [workflow|supervisor|swarm|hybrid]
"""

import os
import sys
import json
import time
import threading
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


# ============ 共享 mock 工具（同 ch03 简化版）============
MOCK_PAGES = {
    "https://example.com/fa3": "FlashAttention-3 在 H100 上比 v2 快 1.5x" * 30,
    "https://example.com/pa-v2": "PagedAttention v2 在 32K+ 比 FA 快 1.8x" * 30,
    "https://example.com/sglang": "SGLang RadixAttention" * 25,
    "https://example.com/vllm": "vLLM 高吞吐" * 25,
    "https://example.com/trtllm": "TRT-LLM NVIDIA 优化" * 25,
}
MOCK_SEARCH = {k: [{"title": k, "url": f"https://example.com/{k.lower().replace(' ', '-')[:8]}",
                    "snippet": f"{k} info"}]
               for k in ["FlashAttention", "PagedAttention", "SGLang", "vLLM", "TensorRT-LLM"]}


def web_search(q):
    time.sleep(0.2)
    for k, r in MOCK_SEARCH.items():
        if k.lower() in q.lower():
            return json.dumps(r, ensure_ascii=False)
    return "[]"


def web_read(url):
    time.sleep(0.5)
    return MOCK_PAGES.get(url, "(not found)")[:5000]


def llm_chat(messages, tools=None):
    return client.chat.completions.create(model=MODEL, messages=messages, tools=tools).choices[0].message


SEARCH_TOOLS = [
    {"type": "function", "function": {"name": "web_search",
        "parameters": {"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]}}},
    {"type": "function", "function": {"name": "web_read",
        "parameters": {"type": "object", "properties": {"url": {"type": "string"}}, "required": ["url"]}}},
]
SEARCH_FNS = {"web_search": web_search, "web_read": web_read}


def search_loop(messages, max_iters=8) -> str:
    for _ in range(max_iters):
        msg = llm_chat(messages, tools=SEARCH_TOOLS)
        messages.append(msg)
        if not msg.tool_calls:
            return msg.content or ""
        for tc in msg.tool_calls:
            args = json.loads(tc.function.arguments)
            try:
                result = SEARCH_FNS[tc.function.name](**args)
            except Exception as e:
                result = f"Error: {e}"
            messages.append({"role": "tool", "tool_call_id": tc.id, "content": result[:4000]})
    return ""


def planner(q):
    m = llm_chat([
        {"role": "system", "content": "把调研问题拆成 3-8 个独立子主题。JSON 数组。"},
        {"role": "user", "content": q},
    ])
    t = m.content or ""
    s, e = t.find("["), t.rfind("]")
    return json.loads(t[s:e+1]) if s >= 0 < e else []


def writer(q, summaries):
    digest = "\n\n".join(f"### {t}\n{s}" for t, s in summaries.items())
    return llm_chat([
        {"role": "system", "content": "基于摘要写一份对比报告（~1500 字）。"},
        {"role": "user", "content": f"问题：{q}\n摘要：\n{digest}"},
    ]).content or ""


# ============ Mode A: Workflow ============
def run_workflow(q):
    topics = planner(q)
    print(f"  topics: {topics}")
    summaries = {}
    with ThreadPoolExecutor(max_workers=len(topics)) as pool:
        futs = {pool.submit(search_loop,
            [{"role": "system", "content": f"调研「{t}」"},
             {"role": "user", "content": f"调研 {t} 并写 300 字摘要"}]): t for t in topics}
        for f in as_completed(futs):
            summaries[futs[f]] = f.result()
    return writer(q, summaries)


# ============ Mode B: Supervisor ============
def run_supervisor(q, max_rounds=12):
    """Supervisor 持续在场，每轮决策下一步。"""
    history = [{"topic": None, "summary": None}]
    summaries = {}
    topics = planner(q)
    pending = list(topics)

    for round_idx in range(max_rounds):
        if not pending and len(summaries) >= len(topics):
            break
        # Supervisor 决策
        decision_prompt = f"""你是调研主管。当前状态：
- 待办主题：{pending}
- 已完成：{list(summaries.keys())}

决定下一步：'search:<topic>' 或 'deepen:<topic>' 或 'stop'。仅返回这一行。"""
        decision = (llm_chat([{"role": "user", "content": decision_prompt}]).content or "").strip()
        print(f"  [round {round_idx}] decision: {decision}")
        if decision.startswith("stop"):
            break
        if decision.startswith("search:") or decision.startswith("deepen:"):
            topic = decision.split(":", 1)[1].strip()
            extra = " 请深入展开" if decision.startswith("deepen:") else ""
            summary = search_loop([
                {"role": "system", "content": f"调研「{topic}」{extra}"},
                {"role": "user", "content": f"调研 {topic}"},
            ])
            summaries[topic] = summary
            if topic in pending:
                pending.remove(topic)
        else:
            break
    return writer(q, summaries)


# ============ Mode C: Swarm ============
def run_swarm(q, max_steps=20):
    """每个 Agent 完成后自主路由。容易死循环——靠 max_steps 兜底。"""
    topics = planner(q)
    summaries = {}
    visited_routes = []
    current = ("search", topics[0]) if topics else ("stop", None)

    for step in range(max_steps):
        kind, payload = current
        print(f"  [step {step}] {kind}:{payload}")
        visited_routes.append(current)
        if kind == "stop":
            break
        if kind == "search":
            summary = search_loop([
                {"role": "system", "content": f"调研「{payload}」"},
                {"role": "user", "content": f"调研 {payload}"},
            ])
            summaries[payload] = summary
            # Agent 自主决定下一步
            done = list(summaries.keys())
            remaining = [t for t in topics if t not in done]
            choice_prompt = f"""刚完成「{payload}」摘要：{summary[:200]}...
剩余主题：{remaining}
下一步：'search:<topic>' 或 'critique:<topic>' 或 'write' 或 'stop'。仅一行。"""
            nxt = (llm_chat([{"role": "user", "content": choice_prompt}]).content or "").strip()
            if nxt.startswith("write"):
                current = ("write", None)
            elif nxt.startswith("stop"):
                current = ("stop", None)
            elif ":" in nxt:
                k, p = nxt.split(":", 1)
                current = (k.strip(), p.strip())
            else:
                current = ("stop", None)
        elif kind == "critique":
            # 简化：critique 后再回去 search 一次
            current = ("search", payload)
        elif kind == "write":
            break
    return writer(q, summaries)


# ============ Mode D: Hybrid (Workflow + 局部 Supervisor) ============
def supervised_search(topic, max_rounds=4):
    """topic 内部一个小 Supervisor，最多 4 轮。"""
    accumulated = []
    for r in range(max_rounds):
        partial = search_loop([
            {"role": "system", "content": f"调研「{topic}」（第 {r+1}/{max_rounds} 轮）。"
                                          + (f"已知：{accumulated[-1][:200]}..." if accumulated else "")},
            {"role": "user", "content": "继续调研，写 200 字增量摘要"},
        ])
        accumulated.append(partial)
        # 简化：让一个轻量 LLM 判断够不够
        check = llm_chat([{"role": "user",
            "content": f"主题「{topic}」当前摘要：\n{partial}\n够全面了吗？回答 'yes' 或 'continue'。"}])
        if (check.content or "").strip().lower().startswith("yes"):
            break
    return "\n".join(accumulated)


def run_hybrid(q):
    topics = planner(q)
    print(f"  topics: {topics}")
    summaries = {}
    with ThreadPoolExecutor(max_workers=len(topics)) as pool:
        futs = {pool.submit(supervised_search, t): t for t in topics}
        for f in as_completed(futs):
            summaries[futs[f]] = f.result()
    return writer(q, summaries)


# ============ 主入口 ============
MODES = {
    "workflow": run_workflow,
    "supervisor": run_supervisor,
    "swarm": run_swarm,
    "hybrid": run_hybrid,
}

if __name__ == "__main__":
    mode = sys.argv[1] if len(sys.argv) > 1 else "hybrid"
    q = "对比 FlashAttention / PagedAttention / SGLang / vLLM / TensorRT-LLM 长上下文场景"
    print(f"=== Mode: {mode} ===")
    if mode not in MODES:
        print(f"unknown mode {mode}; choose from {list(MODES)}"); sys.exit(1)
    t0 = time.time()
    report = MODES[mode](q)
    elapsed = time.time() - t0
    out = WORK / f"report-{mode}.md"
    out.write_text(report)
    print(f"\n=== Done in {elapsed:.1f}s ===\n报告：{out}")
