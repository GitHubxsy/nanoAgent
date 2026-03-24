"""
nano_mcp_http_agent.py - 最小 MCP Agent（Streamable HTTP 版，40 行）
通过 HTTP 请求和远程 MCP Server 通信

用法: python nano_mcp_http_agent.py "What is 3 + 5?"
"""
import os, sys, json, requests
from openai import OpenAI

SERVER_URL = os.environ.get("MCP_SERVER_URL", "http://127.0.0.1:8766/mcp")

# ===== MCP 通信：HTTP POST 发 JSON-RPC，收 JSON 响应 =====

_id = 0
def mcp_send(method, params={}):
    global _id; _id += 1
    resp = requests.post(SERVER_URL, json={"jsonrpc": "2.0", "id": _id, "method": method, "params": params})
    return resp.json()["result"]

# ===== Agent 循环 =====

def run(task):
    mcp_send("initialize", {"protocolVersion": "2024-11-05"})

    tools = [{"type": "function", "function": {"name": t["name"], "description": t["description"], "parameters": t["inputSchema"]}}
             for t in mcp_send("tools/list")["tools"]]

    llm = OpenAI(api_key=os.environ.get("OPENAI_API_KEY"), base_url=os.environ.get("OPENAI_BASE_URL"))
    messages = [{"role": "system", "content": "You are a helpful assistant."}, {"role": "user", "content": task}]

    for _ in range(5):
        msg = llm.chat.completions.create(model=os.environ.get("OPENAI_MODEL", "gpt-4o-mini"), messages=messages, tools=tools).choices[0].message
        messages.append(msg)
        if not msg.tool_calls:
            return msg.content
        for tc in msg.tool_calls:
            args = json.loads(tc.function.arguments)
            print(f"[MCP-HTTP] {tc.function.name}({args})")
            result = mcp_send("tools/call", {"name": tc.function.name, "arguments": args})["content"][0]["text"]
            print(f"  → {result}")
            messages.append({"role": "tool", "tool_call_id": tc.id, "content": result})
    return "Max iterations reached"

if __name__ == "__main__":
    print(run(" ".join(sys.argv[1:]) if len(sys.argv) > 1 else "What is 3 + 5?"))
