"""
Multi-Agent 系列（一）：单 Agent baseline

演示一个会自主搜索、阅读、写报告的单 Agent。
配套文章里说明了它在 4 个地方系统性翻车——这个脚本让你亲眼看到。

跑：
    OPENAI_API_KEY=... python multi-agent-01-when-single-agent-fails.py

注意：web_search / web_read 是 MOCK 实现（返回伪造的搜索结果）。
真实场景请替换成 Tavily / Bing / Serper 等真实 API。
"""

import os
import json
import time
import httpx
from openai import OpenAI

client = OpenAI(
    api_key=os.environ.get("OPENAI_API_KEY"),
    base_url=os.environ.get("OPENAI_BASE_URL"),
    http_client=httpx.Client(verify=False),
)

MODEL = os.environ.get("OPENAI_MODEL", "gpt-4o-mini")


# ============ MOCK 工具实现 ============
# 真实场景换成 Tavily / Bing / Serper 等。

MOCK_SEARCH_DB = {
    "FlashAttention": [
        {"title": "FlashAttention-3 paper (2024)", "url": "https://example.com/fa3",
         "snippet": "FlashAttention-3 leverages async Tensor Cores on H100, 1.5x faster than v2..."},
        {"title": "FlashAttention vs PagedAttention benchmarks (2024 blog)", "url": "https://example.com/fa-vs-pa",
         "snippet": "FlashAttention shows 2.3x speedup over PagedAttention in long-context..."},
    ],
    "PagedAttention": [
        {"title": "vLLM PagedAttention v2 announcement (2025)", "url": "https://example.com/pa-v2",
         "snippet": "PagedAttention v2 outperforms FlashAttention by 1.8x in 32K+ context..."},
        {"title": "PagedAttention paper", "url": "https://example.com/pa-paper",
         "snippet": "Block-based KV cache management reduces memory fragmentation..."},
    ],
    "SGLang": [{"title": "SGLang docs", "url": "https://example.com/sglang", "snippet": "RadixAttention + structured generation..."}],
    "vLLM": [{"title": "vLLM GitHub", "url": "https://example.com/vllm", "snippet": "High-throughput LLM serving..."}],
    "TensorRT-LLM": [{"title": "TensorRT-LLM GitHub", "url": "https://example.com/trtllm", "snippet": "NVIDIA's inference optimization..."}],
}

MOCK_PAGE_DB = {
    "https://example.com/fa3": "FlashAttention-3 论文正文（约 25K tokens 模拟内容，反复几遍就能撑大 context）" * 50,
    "https://example.com/fa-vs-pa": "对比博客（约 8K tokens 模拟内容）" * 20,
    "https://example.com/pa-v2": "PagedAttention v2 公告（约 12K tokens）" * 30,
    "https://example.com/pa-paper": "PagedAttention 论文（约 20K tokens）" * 40,
    "https://example.com/sglang": "SGLang 文档（约 12K tokens）" * 30,
    "https://example.com/vllm": "vLLM 主页（约 8K tokens）" * 20,
    "https://example.com/trtllm": "TensorRT-LLM 主页（约 10K tokens）" * 25,
}


def web_search(query: str) -> str:
    """MOCK：按关键词匹配。"""
    time.sleep(0.5)  # 模拟网络延迟
    for k, results in MOCK_SEARCH_DB.items():
        if k.lower() in query.lower():
            return json.dumps(results, ensure_ascii=False)
    return json.dumps([])


def web_read(url: str) -> str:
    """MOCK：返回页面内容。"""
    time.sleep(1.0)
    return MOCK_PAGE_DB.get(url, f"(页面 {url} 未找到)")[:30000]  # 限制单次最多 30K 字符


def write_file(path: str, content: str) -> str:
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w") as f:
        f.write(content)
    return f"Wrote {len(content)} chars to {path}"


# ============ 工具 schema ============
tools = [
    {"type": "function", "function": {
        "name": "web_search",
        "description": "Search the web. Returns a JSON list of {title, url, snippet}.",
        "parameters": {"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]},
    }},
    {"type": "function", "function": {
        "name": "web_read",
        "description": "Fetch the full content of a URL.",
        "parameters": {"type": "object", "properties": {"url": {"type": "string"}}, "required": ["url"]},
    }},
    {"type": "function", "function": {
        "name": "write_file",
        "description": "Write content to a file.",
        "parameters": {"type": "object",
                       "properties": {"path": {"type": "string"}, "content": {"type": "string"}},
                       "required": ["path", "content"]},
    }},
]
FUNCTIONS = {"web_search": web_search, "web_read": web_read, "write_file": write_file}


SYSTEM_PROMPT = """你是一个技术调研助手。用户给你一个技术问题，你需要：
1. 用 web_search 找相关资料
2. 用 web_read 读取关键页面
3. 综合信息写一份对比报告（约 2000 字）
4. 用 write_file 保存到 work/report-single.md
"""


def run_single_agent(question: str, max_iters: int = 25) -> dict:
    """单 Agent 跑完一次调研，返回统计指标。"""
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": question},
    ]
    stats = {"llm_calls": 0, "tool_calls": 0, "tokens_in": 0, "tokens_out": 0, "elapsed": 0}
    t0 = time.time()

    for i in range(max_iters):
        resp = client.chat.completions.create(model=MODEL, messages=messages, tools=tools)
        stats["llm_calls"] += 1
        if resp.usage:
            stats["tokens_in"] += resp.usage.prompt_tokens
            stats["tokens_out"] += resp.usage.completion_tokens

        msg = resp.choices[0].message
        messages.append(msg)

        if not msg.tool_calls:
            stats["elapsed"] = time.time() - t0
            return stats

        for tc in msg.tool_calls:
            stats["tool_calls"] += 1
            args = json.loads(tc.function.arguments)
            print(f"[Round {i+1}] {tc.function.name}({list(args.keys())})")
            try:
                result = FUNCTIONS[tc.function.name](**args)
            except Exception as e:
                result = f"Error: {e}"
            messages.append({"role": "tool", "tool_call_id": tc.id, "content": result[:8000]})

    stats["elapsed"] = time.time() - t0
    return stats


if __name__ == "__main__":
    question = ("对比 2025-2026 主流 GPU 推理优化方案——FlashAttention、PagedAttention、"
                "SGLang、vLLM、TensorRT-LLM——哪个适合长上下文场景？写一份对比报告。")
    print(f"\n=== Single Agent baseline ===\nQuestion: {question}\n")
    stats = run_single_agent(question)
    print("\n=== 统计 ===")
    for k, v in stats.items():
        print(f"  {k}: {v}")
    print("\n报告写到了 work/report-single.md（如果 Agent 真的写了的话）")
    print("观察点：context 是否爆了？耗时多长？是不是串行？")
