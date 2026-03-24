"""
nano_mcp_http_agent.py - 第一篇的 run_agent 接入 MCP Server

就是第一篇 agent.py 的循环，工具来源从本地硬编码换成了 MCP Server。
没有什么"MCP Client"——就是 run_agent，换了工具来源。

用法: python nano_mcp_http_agent.py "What is 3 + 5?"
"""
import os, sys, json, requests
from openai import OpenAI

SERVER_URL = os.environ.get("MCP_SERVER_URL", "http://127.0.0.1:8766/mcp")
CLIENT = OpenAI(api_key=os.environ.get("OPENAI_API_KEY"), base_url=os.environ.get("OPENAI_BASE_URL"))
MODEL = os.environ.get("OPENAI_MODEL", "gpt-4o-mini")

# ===== MCP 通信：一个函数搞定 =====

_id = 0
def mcp_send(method, params={}):
    global _id; _id += 1
    resp = requests.post(SERVER_URL, json={
        "jsonrpc": "2.0", "id": _id, "method": method, "params": params})
    return resp.json()["result"]

# ===== 还是第一篇的 run_agent =====

def run_agent(task):
    mcp_send("initialize", {"protocolVersion": "2024-11-05"})

    # 从 MCP Server 获取工具列表（第一篇是硬编码的）
    tools = [{"type": "function", "function": {
                "name": t["name"], "description": t["description"],
                "parameters": t["inputSchema"]}}
             for t in mcp_send("tools/list")["tools"]]

    messages = [{"role": "system", "content": "You are a helpful assistant."},
                {"role": "user", "content": task}]

    for _ in range(5):
        msg = CLIENT.chat.completions.create(
            model=MODEL, messages=messages, tools=tools).choices[0].message
        messages.append(msg)
        if not msg.tool_calls:
            return msg.content
        for tc in msg.tool_calls:
            args = json.loads(tc.function.arguments)
            # 通过 MCP Server 执行工具（第一篇是 available_functions[fn](**args)）
            result = mcp_send("tools/call",
                {"name": tc.function.name, "arguments": args})["content"][0]["text"]
            messages.append({"role": "tool", "tool_call_id": tc.id, "content": result})
    return "Max iterations reached"

if __name__ == "__main__":
    print(run_agent(" ".join(sys.argv[1:]) if len(sys.argv) > 1 else "What is 3 + 5?"))
