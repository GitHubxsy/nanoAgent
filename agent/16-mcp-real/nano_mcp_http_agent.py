"""
nano_mcp_http_agent.py - 第一篇的 run_agent 接入 MCP Server

就是第一篇 agent.py 的循环，工具来源从本地硬编码换成了 MCP Server。
没有什么"MCP Client"——就是 run_agent，换了工具来源。

用法: python agent/16-mcp-real/nano_mcp_http_agent.py "What is 3 + 5?"
"""
import os, sys, json, requests
from pathlib import Path
import httpx
from openai import OpenAI


def load_config():
    """从项目根目录的 .agent/config.json 加载配置（API Key、模型等）。"""
    config_path = Path(__file__).resolve().parents[2] / ".agent" / "config.json"
    with open(config_path, "r", encoding="utf-8") as f:
        return json.load(f)


config = load_config()

SERVER_URL = os.environ.get("MCP_SERVER_URL", "http://127.0.0.1:8766/mcp")
CLIENT = OpenAI(
    api_key=config["OPENAI_API_KEY"],
    base_url=config["OPENAI_BASE_URL"],
    http_client=httpx.Client(verify=False),
)
MODEL = config["OPENAI_MODEL"]

# ===== MCP 通信：一个函数搞定 =====

_id = 0
def mcp_send(method, params={}):
    global _id; _id += 1
    resp = requests.post(
        SERVER_URL,
        json={"jsonrpc": "2.0", "id": _id, "method": method, "params": params},
        verify=False,
    )
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
