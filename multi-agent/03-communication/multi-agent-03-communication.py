"""
Multi-Agent 系列（三）：Agent 之间怎么传话——消息 + 文件 + 共享状态

第三版：Searcher 写文件、Planner 用消息分发任务、共享状态做协调（claimed_topics、fetched_urls）。
关键变化：worker 产出（原始资料 + 摘要）落到磁盘，下游按需 read，不直接塞进 message。

跑：
    OPENAI_API_KEY=... python multi-agent-03-communication.py
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

WORK_DIR = Path("./work")
RAW_DIR = WORK_DIR / "raw"
SUMMARY_DIR = WORK_DIR / "summary"
for d in [WORK_DIR, RAW_DIR, SUMMARY_DIR]:
    d.mkdir(parents=True, exist_ok=True)


# ============ 共享状态 ============
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

    def is_url_fetched(self, url: str) -> bool:
        with self._lock:
            return url in self.fetched_urls

    def record_url(self, url: str):
        with self._lock:
            self.fetched_urls.add(url)

    def record_error(self, topic: str, err: str):
        with self._lock:
            self.errors[topic] = err


# ============ MOCK 工具 ============
MOCK_PAGES = {
    "https://example.com/fa3": "FlashAttention-3 论文：在 H100 上利用 async Tensor Cores，比 v2 快 1.5x。" * 30,
    "https://example.com/pa-v2": "PagedAttention v2：在 32K+ 上下文下比 FlashAttention 提速 1.8x。" * 30,
    "https://example.com/sglang": "SGLang：RadixAttention + structured generation。" * 25,
    "https://example.com/vllm": "vLLM：高吞吐 LLM serving，使用 PagedAttention。" * 25,
    "https://example.com/trtllm": "TensorRT-LLM：NVIDIA inference optimization stack。" * 25,
}
MOCK_SEARCH = {
    "FlashAttention": [{"title": "FA3", "url": "https://example.com/fa3", "snippet": "1.5x faster"}],
    "PagedAttention": [{"title": "PA v2", "url": "https://example.com/pa-v2", "snippet": "32K+ wins"}],
    "SGLang": [{"title": "SGLang", "url": "https://example.com/sglang", "snippet": "RadixAttention"}],
    "vLLM": [{"title": "vLLM", "url": "https://example.com/vllm", "snippet": "high throughput"}],
    "TensorRT-LLM": [{"title": "TRT-LLM", "url": "https://example.com/trtllm", "snippet": "NVIDIA"}],
}


def web_search(query: str) -> str:
    time.sleep(0.3)
    for k, results in MOCK_SEARCH.items():
        if k.lower() in query.lower():
            return json.dumps(results, ensure_ascii=False)
    return "[]"


def web_read_with_dedup(url: str, state: SharedState, raw_path: Path) -> str:
    """带去重的 web_read：已抓过的不重复抓。"""
    if state.is_url_fetched(url) and raw_path.exists():
        return f"[from cache] {raw_path.read_text()[:6000]}"
    time.sleep(0.8)
    content = MOCK_PAGES.get(url, f"({url} not found)")
    raw_path.write_text(content)
    state.record_url(url)
    return content[:6000]


# ============ Agents ============
def llm_chat(messages, tools=None):
    return client.chat.completions.create(model=MODEL, messages=messages, tools=tools).choices[0].message


def planner(question: str) -> list[str]:
    msg = llm_chat([
        {"role": "system", "content": "把调研问题拆成 3-8 个独立子主题。返回 JSON 数组（字符串）。"},
        {"role": "user", "content": question},
    ])
    text = msg.content or ""
    start, end = text.find("["), text.rfind("]")
    return json.loads(text[start:end+1]) if start >= 0 < end else []


def searcher(topic: str, state: SharedState) -> dict:
    """搜 + 读 + 总结。把原始资料和摘要分别写到磁盘，只把路径返回。"""
    if not state.claim(topic):
        return {"topic": topic, "skipped": True}

    raw_dir_for_topic = RAW_DIR / topic.replace(" ", "_")
    raw_dir_for_topic.mkdir(exist_ok=True)
    summary_path = SUMMARY_DIR / f"{topic.replace(' ', '_')}.md"

    tools = [
        {"type": "function", "function": {"name": "web_search",
            "parameters": {"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]}}},
        {"type": "function", "function": {"name": "web_read",
            "parameters": {"type": "object", "properties": {"url": {"type": "string"}}, "required": ["url"]}}},
    ]

    messages = [
        {"role": "system", "content": f"你只调研「{topic}」。搜索、阅读、最后写一段 300 字摘要。"},
        {"role": "user", "content": f"调研 {topic}"},
    ]

    for _ in range(8):
        msg = llm_chat(messages, tools=tools)
        messages.append(msg)
        if not msg.tool_calls:
            summary = msg.content or ""
            summary_path.write_text(summary)
            return {"topic": topic, "summary_path": str(summary_path),
                    "raw_dir": str(raw_dir_for_topic)}
        for tc in msg.tool_calls:
            args = json.loads(tc.function.arguments)
            try:
                if tc.function.name == "web_search":
                    result = web_search(**args)
                elif tc.function.name == "web_read":
                    url = args["url"]
                    fname = url.replace("/", "_").replace(":", "")[:80] + ".md"
                    result = web_read_with_dedup(url, state, raw_dir_for_topic / fname)
                else:
                    result = f"unknown tool {tc.function.name}"
            except Exception as e:
                result = f"Error: {e}"
            messages.append({"role": "tool", "tool_call_id": tc.id, "content": result[:5000]})

    return {"topic": topic, "summary_path": str(summary_path), "truncated": True}


def writer(question: str, summary_paths: list[str]) -> str:
    summaries = {Path(p).stem: Path(p).read_text() for p in summary_paths if Path(p).exists()}
    digest = "\n\n".join(f"### {t}\n{s}" for t, s in summaries.items())
    msg = llm_chat([
        {"role": "system", "content": "基于子调研摘要写一份完整对比报告（~1500 字）。"},
        {"role": "user", "content": f"问题：{question}\n\n摘要：\n{digest}"},
    ])
    return msg.content or ""


# ============ 主流程 ============
def run(question: str) -> str:
    state = SharedState()

    print("[Planner] 拆任务...")
    topics = planner(question)
    print(f"[Planner] {topics}")

    print(f"[Searchers] 并行 {len(topics)}...")
    results = []
    t0 = time.time()
    with ThreadPoolExecutor(max_workers=len(topics)) as pool:
        futs = {pool.submit(searcher, t, state): t for t in topics}
        for f in as_completed(futs):
            r = f.result()
            results.append(r)
            print(f"  ✓ {r}")
    print(f"[Searchers] 耗时 {time.time()-t0:.1f}s, 总抓取 URL {len(state.fetched_urls)} 个")

    paths = [r["summary_path"] for r in results if r.get("summary_path")]
    print("[Writer] 整合...")
    report = writer(question, paths)

    out = WORK_DIR / "report-multi-v3.md"
    out.write_text(report)
    print(f"[Writer] 写到 {out}")
    return report


if __name__ == "__main__":
    q = "对比 FlashAttention、PagedAttention、SGLang、vLLM、TensorRT-LLM 在长上下文场景的优劣"
    print(f"=== 第三版：消息 + 文件 + 共享状态 ===\n{q}\n")
    run(q)
