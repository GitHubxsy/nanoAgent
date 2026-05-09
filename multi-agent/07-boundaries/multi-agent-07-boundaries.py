"""
Multi-Agent 系列（七）：边界与反模式——折中方案 demo

演示**单 Agent + SubAgent 临时调用**这个折中方案。
主 Agent 平时自己干，遇到三种场景才召唤 SubAgent：
- 上下文太重的搜索（独立 context）
- 需要独立视角的批判（critic SubAgent）
- 并行子任务（每个塞进 SubAgent）

跑：
    OPENAI_API_KEY=... python multi-agent-07-boundaries.py

读完文章后跑一下，对比第六版 multi-agent 的体感。
"""

import os
import json
import time
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


# ============ Mock 工具（同 ch06 简化）============
MOCK_PAGES = {
    "https://example.com/fa3": "FlashAttention-3 比 v2 快 1.5x" * 30,
    "https://example.com/pa-v2": "PagedAttention v2 比 FA 快 1.8x" * 30,
    "https://example.com/sglang": "SGLang RadixAttention" * 25,
    "https://example.com/vllm": "vLLM 高吞吐" * 25,
    "https://example.com/trtllm": "TRT-LLM NVIDIA 优化" * 25,
}
MOCK_SEARCH = {
    "FlashAttention": [{"title": "FA3", "url": "https://example.com/fa3", "snippet": "1.5x"}],
    "PagedAttention": [{"title": "PA v2", "url": "https://example.com/pa-v2", "snippet": "1.8x"}],
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


def web_read(url):
    time.sleep(0.4)
    return MOCK_PAGES.get(url, "(not found)")[:5000]


def llm(messages, tools=None):
    return client.chat.completions.create(model=MODEL, messages=messages, tools=tools).choices[0].message


# ============ SubAgents（按需召唤、用完即弃）============

def search_subagent(topic: str) -> str:
    """独立 context 的搜索 SubAgent。结果以字符串摘要返回，不污染主 context。"""
    print(f"  └─ [SubAgent:search] {topic}")
    tools = [
        {"type": "function", "function": {"name": "web_search",
            "parameters": {"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]}}},
        {"type": "function", "function": {"name": "web_read",
            "parameters": {"type": "object", "properties": {"url": {"type": "string"}}, "required": ["url"]}}},
    ]
    fns = {"web_search": web_search, "web_read": web_read}
    messages = [
        {"role": "system", "content": f"调研「{topic}」。最后写 250 字摘要。"},
        {"role": "user", "content": f"调研 {topic}"},
    ]
    for _ in range(6):
        msg = llm(messages, tools=tools)
        messages.append(msg)
        if not msg.tool_calls:
            return msg.content or ""
        for tc in msg.tool_calls:
            args = json.loads(tc.function.arguments)
            try:
                result = fns[tc.function.name](**args)
            except Exception as e:
                result = f"Error: {e}"
            messages.append({"role": "tool", "tool_call_id": tc.id, "content": result[:3000]})
    return "(timeout)"


def critic_subagent(report: str) -> list:
    """独立视角批判 SubAgent。"""
    print("  └─ [SubAgent:critic]")
    msg = llm([
        {"role": "system", "content": "找出报告 issues。返回 JSON：[{severity, issue, suggestion}]。宁可挑过头。"},
        {"role": "user", "content": report},
    ])
    t = msg.content or ""
    s, e = t.find("["), t.rfind("]")
    try:
        return json.loads(t[s:e+1]) if s >= 0 < e else []
    except Exception:
        return []


# ============ 主 Agent ============
class MainAgent:
    """单 Agent + 按需召唤 SubAgent。决策权一直在主 Agent。"""

    def run(self, question: str) -> str:
        # Step 1: 主 Agent 自己规划
        print("[Main] 规划...")
        topics = self._plan(question)
        print(f"[Main] topics: {topics}")

        # Step 2: 召唤搜索 SubAgent（可并行）
        print("[Main] 召唤 search SubAgent（并行）")
        summaries = {}
        with ThreadPoolExecutor(max_workers=len(topics)) as pool:
            futs = {pool.submit(search_subagent, t): t for t in topics}
            for f in as_completed(futs):
                summaries[futs[f]] = f.result()

        # Step 3: 主 Agent 自己整合（不召唤 writer SubAgent，因为不需要独立 context）
        print("[Main] 主 Agent 自己整合写作")
        report = self._draft(question, summaries)

        # Step 4: 召唤 critic SubAgent（最多 2 轮）
        for rnd in range(2):
            print(f"[Main] 召唤 critic（round {rnd+1}）")
            issues = critic_subagent(report)
            critical = [i for i in issues if i.get("severity") in ("critical", "major")]
            if not critical:
                break
            report = self._revise(question, summaries, report, issues)

        return report

    def _plan(self, q):
        m = llm([
            {"role": "system", "content": "把问题拆成 3-8 独立子主题。JSON 数组，每个元素是字符串。"},
            {"role": "user", "content": q},
        ])
        t = m.content or ""
        s, e = t.find("["), t.rfind("]")
        if not (s >= 0 < e):
            return []
        items = json.loads(t[s:e+1]) if s >= 0 < e else []
        return [
            item if isinstance(item, str)
            else item.get("主题") or item.get("topic") or item.get("subtopic") or item.get("name") or str(item)
            for item in items
        ]

    def _draft(self, q, summaries):
        digest = "\n\n".join(f"### {t}\n{s}" for t, s in summaries.items())
        m = llm([
            {"role": "system", "content": "基于摘要写对比报告（~1500 字）。"},
            {"role": "user", "content": f"问题：{q}\n摘要：\n{digest}"},
        ])
        return m.content or ""

    def _revise(self, q, summaries, prev, issues):
        digest = "\n\n".join(f"### {t}\n{s}" for t, s in summaries.items())
        m = llm([
            {"role": "system", "content": "基于上一版报告 + critic 反馈，写出修订版。"},
            {"role": "user", "content": f"问题：{q}\n摘要：\n{digest}\n\n上一版：\n{prev}\n\n反馈：\n"
                                          + json.dumps(issues, ensure_ascii=False, indent=2)},
        ])
        return m.content or ""


if __name__ == "__main__":
    q = "对比 FlashAttention / PagedAttention / SGLang / vLLM / TensorRT-LLM 长上下文场景"
    print(f"=== 第七章：单 Agent + SubAgent 折中方案 ===\n{q}\n")
    t0 = time.time()
    report = MainAgent().run(q)
    elapsed = time.time() - t0
    out = WORK / "report-hybrid-subagent.md"
    out.write_text(report)
    print(f"\n[Done] {elapsed:.1f}s, 报告：{out}")
    print("\n对比要点：")
    print("- 这个版本没有 Scratchpad（共享状态），但有并行 SubAgent")
    print("- 没有 Workflow / Supervisor 这种持久编排，决策权一直在 MainAgent")
    print("- 代码量比第六版少约 40%")
    print("- 适合：满足 2/3 条件（并行 + 上下文隔离）但不需要复杂状态共享的场景")
