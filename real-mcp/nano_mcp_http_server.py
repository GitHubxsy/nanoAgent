"""
nano_mcp_http_server.py - 最小 MCP Server（Streamable HTTP 版）
一个 HTTP 端点处理所有 JSON-RPC 请求

用法: python nano_mcp_http_server.py
"""
import json
from http.server import HTTPServer, BaseHTTPRequestHandler

# ===== 工具注册 =====

TOOLS = {
    "add": {
        "desc": "Add two numbers",
        "schema": {
            "type": "object",
            "properties": {"a": {"type": "number"}, "b": {"type": "number"}},
            "required": ["a", "b"],
        },
        "fn": lambda a, b: a + b,
    },
    "multiply": {
        "desc": "Multiply two numbers",
        "schema": {
            "type": "object",
            "properties": {"a": {"type": "number"}, "b": {"type": "number"}},
            "required": ["a", "b"],
        },
        "fn": lambda a, b: a * b,
    },
    "weather": {
        "desc": "Get weather for a city",
        "schema": {
            "type": "object",
            "properties": {"city": {"type": "string"}},
            "required": ["city"],
        },
        "fn": lambda city: f"{city}: Sunny 25°C",
    },
}

# ===== 处理三种 MCP 请求 =====

def handle(method, params):
    if method == "initialize":
        return {"protocolVersion": "2024-11-05", "capabilities": {"tools": {}}}
    if method == "tools/list":
        return {"tools": [
            {"name": n, "description": t["desc"], "inputSchema": t["schema"]}
            for n, t in TOOLS.items()
        ]}
    if method == "tools/call":
        result = TOOLS[params["name"]]["fn"](**params.get("arguments", {}))
        return {"content": [{"type": "text", "text": str(result)}]}

# ===== HTTP 端点：收 POST 请求，返 JSON 响应 =====

class MCPHandler(BaseHTTPRequestHandler):
    def do_POST(self):
        msg = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        result = handle(msg["method"], msg.get("params", {}))
        body = json.dumps({"jsonrpc": "2.0", "id": msg["id"], "result": result}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(body)
    def log_message(self, *a): pass

if __name__ == "__main__":
    print("MCP Server running on http://127.0.0.1:8766/mcp")
    HTTPServer(("127.0.0.1", 8766), MCPHandler).serve_forever()
