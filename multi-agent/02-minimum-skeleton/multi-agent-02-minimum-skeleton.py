"""
Multi-Agent 系列（二）：最小多 Agent 骨架

Workflow 模式：1 Planner + N Searcher（并行）+ 1 Writer。
每个 Searcher 独立 context，只把字符串摘要交回 Planner。

跑：
    OPENAI_API_KEY=... python multi-agent-02-minimum-skeleton.py

依赖：上一章的 mock 工具（这里复制过来，正式 demo 应抽到共享模块）。
"""

import os
import json
import time
import httpx
from concurrent.futures import ThreadPoolExecutor, as_completed
from openai import OpenAI

client = OpenAI(
    api_key=os.environ.get("OPENAI_API_KEY"),
    base_url=os.environ.get("OPENAI_BASE_URL"),
    http_client=httpx.Client(verify=False),
)
MODEL = os.environ.get("OPENAI_MODEL", "gpt-4o-mini")


# ============ MOCK 工具（同 ch01）============
MOCK_SEARCH_DB = {
    "FlashAttention": [{"title": "FA3", "url": "https://example.com/fa3", "snippet": "FA3 1.5x faster than v2..."}],
    "PagedAttention": [{"title": "PA v2", "url": "https://example.com/pa-v2", "snippet": "PA v2 outperforms FA in 32K+..."}],
    "SGLang": [{"title": "SGLang", "url": "https://example.com/sglang", "snippet": "RadixAttention..."}],
    "vLLM": [{"title": "vLLM", "url": "https://example.com/vllm", "snippet": "High-throughput..."}],
    "TensorRT-LLM": [{"title": "TRT-LLM", "url": "https://example.com/trtllm", "snippet": "NVIDIA optimization..."}],
}
MOCK_PAGE_DB = {url: f"页面 {url} 的正文内容（模拟约 5K tokens）" * 30
                for results in MOCK_SEARCH_DB.values() for r in results for url in [r["url"]]}


def web_search(query: str) -> str:
    time.sleep(0.3)
    for k, results in MOCK_SEARCH_DB.items():
        if k.lower() in query.lower():
            return json.dumps(results, ensure_ascii=False)
    return "[]"


def web_read(url: str) -> str:
    time.sleep(0.8)
    return MOCK_PAGE_DB.get(url, f"({url} not found)")[:8000]


SEARCH_TOOLS = [
    {"type": "function", "function": {
        "name": "web_search", "description": "Search the web",
        "parameters": {"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]}}},
    {"type": "function", "function": {
        "name": "web_read", "description": "Read a URL",
        "parameters": {"type": "object", "properties": {"url": {"type": "string"}}, "required": ["url"]}}},
]
SEARCH_FNS = {"web_search": web_search, "web_read": web_read}


# ============ Agents ============

def llm_chat(messages, tools=None) -> dict:
    """统一 LLM 调用，返回 {message, usage}。"""
    resp = client.chat.completions.create(model=MODEL, messages=messages, tools=tools)
    return {"message": resp.choices[0].message, "usage": resp.usage}


def planner(question: str) -> list[str]:
    """拆任务。返回 topic 列表。"""
    out = llm_chat([
        {"role": "system", "content": "你是规划助手。把调研问题拆成 3-8 个独立、不重叠的子调研主题。"
                                       "返回 JSON 数组，元素是字符串。"},
        {"role": "user", "content": question},
    ])
    text = out["message"].content or ""
    # 简单提取 JSON 数组
    start = text.find("[")
    end = text.rfind("]")
    if start >= 0 and end > start:
        return json.loads(text[start:end+1])
    return []


def searcher(topic: str, max_iters: int = 8) -> str:
    """每个 worker 独立 context。返回摘要字符串。"""
    messages = [
        {"role": "system", "content": f"你是专项调研员，只调研「{topic}」。"
                                       f"通过 web_search + web_read 收集资料，最后用一段话（200-400 字）总结："
                                       f"包括核心思路、性能数据、适用场景。"},
        {"role": "user", "content": f"调研 {topic}"},
    ]
    for _ in range(max_iters):
        out = llm_chat(messages, tools=SEARCH_TOOLS)
        msg = out["message"]
        messages.append(msg)
        if not msg.tool_calls:
            return msg.content or "(空摘要)"
        for tc in msg.tool_calls:
            args = json.loads(tc.function.arguments)
            try:
                result = SEARCH_FNS[tc.function.name](**args)
            except Exception as e:
                result = f"Error: {e}"
            messages.append({"role": "tool", "tool_call_id": tc.id, "content": result[:6000]})
    return "(超过迭代上限)"


def writer(question: str, summaries: dict[str, str]) -> str:
    """整合所有摘要写报告。"""
    digest = "\n\n".join(f"### {t}\n{s}" for t, s in summaries.items())
    out = llm_chat([
        {"role": "system", "content": "你是技术编辑。基于多份子调研摘要，写一份完整的对比报告（~1500 字）。"},
        {"role": "user", "content": f"问题：{question}\n\n各子调研摘要：\n{digest}"},
    ])
    return out["message"].content or ""


# ============ 主流程 ============

def run_workflow(question: str) -> str:
    print("\n[Planner] 拆任务...")
    topics = planner(question)
    print(f"[Planner] 得到 {len(topics)} 个主题：{topics}")

    print(f"\n[Searchers] 并行启动 {len(topics)} 个 worker...")
    summaries = {}
    t0 = time.time()
    with ThreadPoolExecutor(max_workers=len(topics)) as pool:
        futures = {pool.submit(searcher, t): t for t in topics}
        for fut in as_completed(futures):
            t = futures[fut]
            try:
                summaries[t] = fut.result()
                print(f"[Searcher:{t}] 完成 ({len(summaries[t])} chars)")
            except Exception as e:
                summaries[t] = f"(失败: {e})"
                print(f"[Searcher:{t}] 失败：{e}")
    print(f"[Searchers] 总耗时 {time.time()-t0:.1f}s")

    print("\n[Writer] 整合报告...")
    report = writer(question, summaries)

    out_path = "work/report-multi-v2.md"
    os.makedirs("work", exist_ok=True)
    with open(out_path, "w") as f:
        f.write(report)
    print(f"[Writer] 报告写到 {out_path}")
    return report


if __name__ == "__main__":
    question = "对比 FlashAttention、PagedAttention、SGLang、vLLM、TensorRT-LLM 在长上下文场景的优劣"
    print(f"=== 第二版：Workflow 多 Agent ===\nQuestion: {question}")
    run_workflow(question)
