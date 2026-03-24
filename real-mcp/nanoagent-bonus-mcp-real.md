# 从零开始理解 Agent（番外篇）：真正的 MCP 长什么样？107 行代码实现完整 MCP Server + Agent 接入

> 在系列第三篇中，我们讲了 MCP 的概念——"AI 世界的 USB 接口"，但那个实现是简化版的（只读了配置文件中的工具 schema，没有真正的 server 通信）。很多读者留言想看"真正的 MCP 是怎么跑起来的"。
>
> 今天我们用 107 行代码（server 62 行 + agent 45 行），基于 MCP 规范推荐的 **Streamable HTTP** 传输方式，实现一个完整的、能跑的 MCP。Agent 端就是第一篇的 `run_agent`，没有任何新概念。

-----

## 一、先回忆：第三篇中的 MCP 是什么样的？

在系列第三篇中，agent-claudecode.py 的 MCP 实现是这样的：

```python
# 读取配置文件
with open(".agent/mcp.json") as f:
    config = json.load(f)

# 把工具 schema 加入 tools 列表
for tool in server.get("tools", []):
    mcp_tools.append({"type": "function", "function": tool})
```

本质上就是**读了一个 JSON 文件，把里面的工具描述塞进了 tools 列表**。没有 server，没有 client，没有通信协议。

这对于理解"MCP 的作用是什么"已经足够了，但真正的 MCP 不是这么工作的。真正的 MCP 有两个独立的进程在通过 HTTP 通信。

-----

## 二、真正的 MCP：两个进程通过 HTTP 对话

```
┌─────────────────┐       HTTP POST / JSON       ┌─────────────────┐
│   Agent          │  ──── JSON-RPC 请求 ────▶   │   MCP Server     │
│  (第一篇的循环)   │  ◀──── JSON-RPC 响应 ────   │  (工具提供方)     │
└─────────────────┘                               └─────────────────┘
    任何机器                                         任何机器
```

**MCP Server** 是一个独立的 HTTP 服务，暴露一组工具（比如 add、multiply、weather）。它不知道 LLM 的存在，只知道"有人会通过 HTTP 发 JSON-RPC 来问我有哪些工具、来调用我的工具"。

**Agent 端**就是第一篇的 `run_agent`，没有任何新概念。唯一的变化是：工具不再硬编码在代码里，而是通过 HTTP 从 MCP Server 动态获取和调用。

它们之间的通信用 **JSON-RPC 2.0** 协议，传输方式是 **HTTP POST**——client 发一个 POST 请求，server 返回一个 JSON 响应。就是最普通的 HTTP 接口调用。

-----

## 三、MCP Server：62 行代码

```python
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
```

### 3.1 工具注册表

还记得第一篇中的 `available_functions` 吗？

```python
# 第一篇 agent.py 中的工具注册
available_functions = {
    "execute_bash": execute_bash,
    "read_file": read_file,
}
```

MCP Server 的 `TOOLS` 是同一个思路，只是多了 `desc` 和 `schema`——因为 server 需要把这些信息通过 HTTP 告诉 client，client 再转给 LLM。

### 3.2 请求处理：只有三个方法

整个 MCP Server 只需要处理三种请求：

|方法          |作用       |类比      |
|------------|---------|--------|
|`initialize`|握手，告知协议版本|TCP 三次握手|
|`tools/list`|返回所有工具列表 |`ls` 命令 |
|`tools/call`|执行指定工具   |函数调用    |

就这三个。没有认证，没有会话管理——最小可行 MCP。

### 3.3 HTTP 端点

```python
class MCPHandler(BaseHTTPRequestHandler):
    def do_POST(self):
        msg = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        result = handle(msg["method"], msg.get("params", {}))
        body = json.dumps({"jsonrpc": "2.0", "id": msg["id"], "result": result}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(body)
```

和写一个普通的 HTTP API 完全一样：读 POST Body → 处理 → 返回 JSON。如果你写过 Flask 或 FastAPI，这个代码毫无门槛。

-----

## 四、Agent 端：还是第一篇的 run_agent

回顾第一篇 agent.py 的核心循环：初始化 messages → 调用 LLM → 判断有没有 tool_calls → 有就执行工具 → 结果塞回 messages → 继续循环。

下面这段代码和第一篇**结构完全一样**，唯一的区别是工具不再硬编码，而是通过 `mcp_send` 从 MCP Server 获取和调用：

```python
import os, sys, json, requests
from openai import OpenAI

SERVER_URL = os.environ.get("MCP_SERVER_URL", "http://127.0.0.1:8766/mcp")

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

    llm = OpenAI(api_key=os.environ.get("OPENAI_API_KEY"),
                 base_url=os.environ.get("OPENAI_BASE_URL"))
    messages = [{"role": "system", "content": "You are a helpful assistant."},
                {"role": "user", "content": task}]

    for _ in range(5):
        msg = llm.chat.completions.create(
            model=os.environ.get("OPENAI_MODEL", "gpt-4o-mini"),
            messages=messages, tools=tools).choices[0].message
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
```

### 4.1 MCP 通信：一个函数搞定

```python
def mcp_send(method, params={}):
    resp = requests.post(SERVER_URL, json={
        "jsonrpc": "2.0", "id": _id, "method": method, "params": params})
    return resp.json()["result"]
```

整个 MCP 通信就是一个 `requests.post()`——发一个 JSON，收一个 JSON。这不是什么新概念，就是一个 HTTP 调用。

### 4.2 获取工具 + 格式转换

```python
tools = [{"type": "function", "function": {
            "name": t["name"], "description": t["description"],
            "parameters": t["inputSchema"]}}
         for t in mcp_send("tools/list")["tools"]]
```

Agent 调用 `tools/list` 从 server 拿到工具列表，转换成 OpenAI 的 tools 格式。这一步是"适配器"——MCP 工具格式和 OpenAI 工具格式略有不同，需要转一下。

### 4.3 和第一篇的唯一区别

|    |第一篇 agent.py                     |本文 agent（接入 MCP）                        |
|----|---------------------------------|----------------------------------------|
|工具来源|代码里硬编码                           |`mcp_send("tools/list")` 从 server 动态获取  |
|工具执行|`available_functions[fn](**args)`|`mcp_send("tools/call", ...)` 通过 HTTP 调用|
|循环结构|完全一样                             |完全一样                                    |

**没有什么"MCP Client"。** 就是第一篇的 `run_agent`，把工具来源从本地字典换成了 HTTP 请求。MCP 只是把"工具从哪来、怎么执行"这一层抽象出去了，Agent 循环本身一个字没变。

-----

## 五、完整通信流程

用一个具体例子来看整个过程：

```
用户: "What is 3 + 5?"

[Client → Server] POST http://127.0.0.1:8766/mcp
  Body: {"method": "initialize", "params": {"protocolVersion": "2024-11-05"}}
[Server → Client] 200 OK
  Body: {"result": {"protocolVersion": "2024-11-05", "capabilities": {"tools": {}}}}

[Client → Server] POST http://127.0.0.1:8766/mcp
  Body: {"method": "tools/list"}
[Server → Client] 200 OK
  Body: {"result": {"tools": [
    {"name": "add", "description": "Add two numbers", "inputSchema": {...}},
    {"name": "multiply", ...},
    {"name": "weather", ...}
  ]}}

[Client] 把 MCP 工具转换成 OpenAI 格式，发给 LLM
[LLM 返回] tool_calls: [{"name": "add", "arguments": {"a": 3, "b": 5}}]

[Client → Server] POST http://127.0.0.1:8766/mcp
  Body: {"method": "tools/call", "params": {"name": "add", "arguments": {"a": 3, "b": 5}}}
[Server → Client] 200 OK
  Body: {"result": {"content": [{"type": "text", "text": "8"}]}}

[Client] 把结果 "8" 返回给 LLM
[LLM 返回] "3 + 5 = 8"
```

三次 HTTP POST，整个过程完成：**initialize → tools/list → tools/call**。

-----

## 六、运行方式

```bash
# 终端 1：启动 MCP Server
python nano_mcp_http_server.py
# 输出: MCP Server running on http://127.0.0.1:8766/mcp

# 终端 2：运行 Agent
python nano_mcp_http_agent.py "What is 3 + 5?"
# 输出:
# [MCP] add({"a": 3, "b": 5})
#   → 8
# 3 + 5 = 8
```

Server 是独立运行的 HTTP 服务。这意味着它可以跑在任何机器上——本地、远程服务器、Docker 容器、甚至云函数。Client 只需要知道 URL 就能连接。

想换一个远程 MCP Server？改一行环境变量就行：

```bash
export MCP_SERVER_URL="https://your-remote-server.com/mcp"
python nano_mcp_http_agent.py "What's the weather in Beijing?"
```

-----

## 七、本文 vs 第三篇的简化版

|      |第三篇 agent-claudecode.py|本文 MCP 实现                  |
|------|-----------------------|---------------------------|
|Server|无（只有一个 JSON 配置文件）      |独立 HTTP 服务，处理 JSON-RPC     |
|Client|无（直接读配置）               |HTTP POST 发请求、收响应          |
|通信协议  |无                      |JSON-RPC 2.0 over HTTP     |
|工具发现  |读文件                    |`tools/list` 动态查询          |
|工具执行  |本地函数调用                 |`tools/call` 跨进程 HTTP 调用   |
|可以远程吗 |不行                     |可以，改 URL 就行                |
|代码量   |5 行                    |107 行（server 62 + agent 45）|

**第三篇是"MCP 的思想"，本文是"MCP 的实现"。** 思想一样——工具的描述和执行分离；实现不同——一个读文件，一个走 HTTP 协议。

-----

## 八、MCP 的三种传输方式

本文用的是 Streamable HTTP，MCP 规范实际上定义了三种传输方式：

|     |stdio          |SSE                 |Streamable HTTP|
|-----|---------------|--------------------|---------------|
|通信方式 |stdin/stdout 管道|HTTP POST + SSE 流式响应|普通 HTTP 请求/响应  |
|需要网络吗|不需要，纯本地        |需要                  |需要             |
|适用场景 |本地工具           |远程 + 流式响应           |远程 + 简单请求响应    |
|类比   |面对面说话          |打电话                 |发微信            |
|状态   |常用于本地          |**过渡方案，正在被取代**      |**MCP 规范推荐**   |

三种方式的 JSON-RPC 消息格式完全一样（都是 `initialize` → `tools/list` → `tools/call`），区别只在"消息怎么送达"。

**怎么选？** 工具在本地用 stdio，工具在远程用 Streamable HTTP。SSE 是过渡方案，新项目不建议用。

-----

## 九、一句话总结

**MCP 的本质就是：Server 暴露工具、Agent 通过 JSON-RPC 查询和调用工具、HTTP 是它们之间的管道。没有什么"MCP Client"——就是第一篇的 `run_agent`，换了工具来源。**

107 行代码，两个文件，一个完整的 MCP。

如果你已经读懂了第一篇中的 Agent 循环，那 MCP 对你来说只是把 `available_functions[fn](**args)` 换成了 `mcp_send("tools/call", ...)`——一个本地函数调用变成了一次 HTTP 请求。其他一切都没变。

-----

*完整 Agent 系列见 [GitHub 仓库](https://github.com/GitHubxsy/nanoAgent)。*
