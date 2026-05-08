"""
Multi-Agent 系列（五）：状态、记忆与上下文——Scratchpad

第五版：在第四版基础上引入 Scratchpad（共享便签）：
- 事实层（fetched_urls, claimed_topics）：worker 自由读写做去重
- 判断层（key_findings, conflicts）：worker 只写，汇总阶段（Writer）才读
- 加上 conflict-detector：在 Writer 之前找出对立论断

跑：
    OPENAI_API_KEY=... python multi-agent-05-state-memory.py
"""

import os
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


# ============ Scratchpad ============
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

    # 事实层 API
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

    # 判断层 API（只让 Searcher 写、Writer 读）
    def add_finding(self, topic, claim, source):
        with self._lock:
            self.key_findings.setdefault(topic, []).append({"claim": claim, "source": source})

    def add_conflict(self, conflict):
        with self._lock:
            self.conflicts.append(conflict)

    def snapshot_for_writer(self):
        with self._lock:
            return {"key_findings": dict(self.key_findings),
                    "conflicts": list(self.conflicts)}


# ============ Mock 工具 ============
MOCK_PAGES = {
    "https://example.com/fa3": "FlashAttention-3 比 v2 快 1.5x（H100, 8K context）" * 30,
    "https://example.com/fa-vs-pa-2024": "FlashAttention 比 PagedAttention 快 2.3x（FA team blog 2024, 8K）" * 30,
    "https://example.com/pa-v2-2025": "PagedAttention v2 比 FlashAttention 快 1.8x（vLLM team 2025, 32K）" * 30,
    "https://example.com/sglang": "SGLang RadixAttention" * 25,
    "https://example.com/vllm": "vLLM 高吞吐" * 25,
    "https://example.com/trtllm": "TRT-LLM NVIDIA 优化" * 25,
}
MOCK_SEARCH = {
    "FlashAttention": [{"title": "FA3", "url": "https://example.com/fa3", "snippet": "1.5x"},
                       {"title": "FA vs PA 2024", "url": "https://example.com/fa-vs-pa-2024", "snippet": "2.3x"}],
    "PagedAttention": [{"title": "PA v2 2025", "url": "https://example.com/pa-v2-2025", "snippet": "1.8x"}],
    "SGLang": [{"title": "SGLang", "url": "https://example.com/sglang", "snippet": "RA"}],
    "vLLM": [{"title": "vLLM", "url": "https://example.com/vllm", "snippet": "throughput"}],
    "TensorRT-LLM": [{"title": "TRT-LLM", "url": "https://example.com/trtllm", "snippet": "NVIDIA"}],
}


def web_search(q):
    time.sleep(0.2)
    for k, r in MOCK_SEARCH.items():
        if k.lower() in q.lower():
            return json.dumps(r, ensure_ascii=False)
    return "[]"


def web_read_dedup(url, scratch: Scratchpad):
    if scratch.is_fetched(url):
        return f"[cached] {MOCK_PAGES.get(url, '')[:3000]}"
    time.sleep(0.5)
    scratch.record_url(url)
    return MOCK_PAGES.get(url, "(not found)")[:5000]


def llm(messages, tools=None):
    return client.chat.completions.create(model=MODEL, messages=messages, tools=tools).choices[0].message


SEARCH_TOOLS = [
    {"type": "function", "function": {"name": "web_search",
        "parameters": {"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]}}},
    {"type": "function", "function": {"name": "web_read",
        "parameters": {"type": "object", "properties": {"url": {"type": "string"}}, "required": ["url"]}}},
]


# ============ Agents ============
def planner(q):
    m = llm([
        {"role": "system", "content": "把问题拆成 3-8 独立子主题。JSON 数组。"},
        {"role": "user", "content": q},
    ])
    t = m.content or ""
    s, e = t.find("["), t.rfind("]")
    return json.loads(t[s:e+1]) if s >= 0 < e else []


def searcher(topic, scratch: Scratchpad) -> str:
    """搜 + 读（带去重）+ 总结 + 把 key findings 挂到 scratchpad。"""
    if not scratch.claim(topic):
        return f"({topic} 已被认领)"

    messages = [
        {"role": "system", "content": f"调研「{topic}」。最后写一段 300 字摘要。"
                                       "另外提炼 2-3 个 key findings：每条说明论断 + 来源 URL。"
                                       "把 key findings 用 KEY:claim|source 这种格式单独列在最后。"},
        {"role": "user", "content": f"调研 {topic}"},
    ]
    summary_text = ""
    for _ in range(8):
        msg = llm(messages, tools=SEARCH_TOOLS)
        messages.append(msg)
        if not msg.tool_calls:
            summary_text = msg.content or ""
            break
        for tc in msg.tool_calls:
            args = json.loads(tc.function.arguments)
            try:
                if tc.function.name == "web_search":
                    result = web_search(**args)
                elif tc.function.name == "web_read":
                    result = web_read_dedup(args["url"], scratch)
                else:
                    result = "unknown"
            except Exception as e:
                result = f"Error: {e}"
            messages.append({"role": "tool", "tool_call_id": tc.id, "content": result[:4000]})

    # 提取 key findings 写入 scratchpad
    for line in summary_text.splitlines():
        if line.startswith("KEY:") and "|" in line:
            try:
                claim, source = line[4:].split("|", 1)
                scratch.add_finding(topic, claim.strip(), source.strip())
            except Exception:
                pass
    return summary_text


def detect_conflicts(scratch: Scratchpad):
    """让 LLM 找出对立论断。"""
    findings = scratch.snapshot_for_writer()["key_findings"]
    if not findings:
        return []
    flat = [{"topic": t, **f} for t, fs in findings.items() for f in fs]
    prompt = ("以下是从多个来源摘出的论断。找出**互相矛盾**的论断对。\n"
              "每对返回：{a, b, why_conflict, possible_reason}（JSON 数组）。无冲突返回 []。\n\n"
              + json.dumps(flat, ensure_ascii=False))
    text = (llm([{"role": "user", "content": prompt}]).content or "")
    try:
        s, e = text.find("["), text.rfind("]")
        conflicts = json.loads(text[s:e+1]) if s >= 0 < e else []
    except Exception:
        conflicts = []
    for c in conflicts:
        scratch.add_conflict(c)
    return conflicts


def writer(q, summaries, scratch: Scratchpad):
    snapshot = scratch.snapshot_for_writer()
    digest = "\n\n".join(f"### {t}\n{s}" for t, s in summaries.items())
    extra = ""
    if snapshot["conflicts"]:
        extra = "\n\n冲突标记：\n" + json.dumps(snapshot["conflicts"], ensure_ascii=False, indent=2)
    msg = llm([
        {"role": "system", "content": "基于摘要 + 冲突标记写一份对比报告（~1500 字）。"
                                       "对冲突论断要明确说明分歧并给读者建议。"},
        {"role": "user", "content": f"问题：{q}\n摘要：\n{digest}{extra}"},
    ])
    return msg.content or ""


# ============ 主流程 ============
def run(q):
    scratch = Scratchpad()
    print("[Planner]")
    topics = planner(q)
    print(f"  topics: {topics}")

    print(f"[Searchers] 并行 {len(topics)}")
    summaries = {}
    with ThreadPoolExecutor(max_workers=len(topics)) as pool:
        futs = {pool.submit(searcher, t, scratch): t for t in topics}
        for f in as_completed(futs):
            summaries[futs[f]] = f.result()
    print(f"  fetched URLs: {len(scratch.fetched_urls)}")
    print(f"  key findings: {sum(len(v) for v in scratch.key_findings.values())}")

    print("[Conflict Detector]")
    conflicts = detect_conflicts(scratch)
    print(f"  conflicts: {len(conflicts)}")

    print("[Writer]")
    report = writer(q, summaries, scratch)
    out = WORK / "report-multi-v5.md"
    out.write_text(report)
    print(f"  写到 {out}")
    return report


if __name__ == "__main__":
    q = "对比 FlashAttention / PagedAttention / SGLang / vLLM / TensorRT-LLM 长上下文场景"
    print(f"=== 第五版：Scratchpad + Conflict Detector ===\n{q}\n")
    run(q)
