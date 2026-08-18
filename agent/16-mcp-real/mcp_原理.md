# MCP 原理详解

> 本文结合 `nano_mcp_http_server.py` 和 `nano_mcp_http_agent.py` 两个文件，向完全不了解 MCP 的读者讲清楚 MCP 到底是什么。

---

# 一、先讲清楚：MCP 到底解决什么问题？

## 一个生活类比：USB-C 接口

你想想现在的电子产品——手机、硬盘、显示器、键盘……每个都能用同一个 **USB-C 接口** 插上去用。你不用关心键盘是哪家厂做的，也不用关心它内部怎么工作，**只要它长着 USB-C 的形状，插上就能用**。

在 AI 出现之前，如果想让一个 AI 助手调用外部工具（比如查天气、读文件、算数学），是这样的局面：

```
查天气的接口    →  每个AI都要单独写一套对接代码
读文件的接口    →  每个AI都要单独写一套对接代码
查数据库的接口  →  每个AI都要单独写一套对接代码
```

每接一个工具，AI 那边就得改一次代码。工具一多，就乱成一锅粥。**这就好比每个外设都长着自己的专属插头，插哪个电脑都得单独配插座。**

**MCP（Model Context Protocol，模型上下文协议）就是给 AI 世界统一设计的那个 "USB-C 接口"。** 只要工具按 MCP 标准做，任何支持 MCP 的 AI 都能直接调用它，不用为每个工具单独写代码。

---

## 另一个更贴切的类比：餐厅点菜

理解这个之后，再看代码就非常简单了。把 MCP 想象成一家餐厅：

| 餐厅角色 | 对应 MCP 里的东西 | 代码文件 |
|---------|-----------------|---------|
| **后厨**（会做菜，但不直接见客人） | **MCP Server**（工具的提供方） | `nano_mcp_http_server.py` |
| **顾客**（想吃饭，但不会做） | **Agent / AI**（工具的使用方） | `nano_mcp_http_agent.py` |
| **服务员**（在桌子和后厨之间跑腿） | **HTTP + JSON-RPC**（通信方式） | `mcp_send()` 函数 |
| **要一份菜单** | `tools/list` | "你们有什么工具？" |
| **点一道菜** | `tools/call` | "帮我执行 add 工具" |
| **进门打个招呼** | `initialize` | 握手打招呼 |

顾客（AI）根本不需要知道后厨（Server）是怎么炒菜的，**只要会看菜单、会点菜就行**。这就是 MCP 的核心思想：**工具的"描述"和"执行"彻底分开，通过一个统一协议交流。**

---

# 二、整体架构图

两个**独立运行的进程**，通过网络对话：

```
   ┌─────────────────────────┐              ┌──────────────────────────┐
   │     Agent (顾客)         │              │    MCP Server (后厨)      │
   │  nano_mcp_http_agent.py  │              │ nano_mcp_http_server.py   │
   │                         │              │                          │
   │  ┌───────────────────┐  │   HTTP POST  │  ┌────────────────────┐  │
   │  │ LLM (大脑)         │  │  ──────────▶ │  │ 工具注册表 TOOLS    │  │
   │  │ "3+5=? 我要用      │  │   JSON-RPC   │  │  add / multiply /  │  │
   │  │  add 工具"         │  │  ◀────────── │  │  weather           │  │
   │  └───────────────────┘  │              │  └────────────────────┘  │
   │                         │   ①initialize │                          │
   │   run_agent 循环：       │   ②tools/list│   handle() 处理三种请求   │
   │   拿菜单→问LLM→点菜→    │   ③tools/call│                          │
   │   拿结果→给LLM          │              │                          │
   └─────────────────────────┘              └──────────────────────────┘
        可以是任何一台机器                      可以是任何一台机器
     （本地 / 远程服务器 / 云）                （本地 / 远程 / Docker）
```

**关键点**：Server 不知道有 LLM 的存在，它只知道"有人会发 HTTP 请求问我有没有工具、要调用我的工具"。两边的解耦做得非常彻底——这就是为什么 MCP Server 能跑在任何地方。

---

# 三、逐段讲代码

## 第一部分：MCP Server（后厨）—— `nano_mcp_http_server.py`

这个文件就干三件事：**注册工具 → 处理请求 → 当 HTTP 服务**。

### ① 工具注册表 —— 后厨的菜单

```python
TOOLS = {
    "add": {
        "desc": "Add two numbers",          # 这道菜叫什么
        "schema": {                          # 这道菜需要什么食材（参数）
            "type": "object",
            "properties": {"a": {"type": "number"}, "b": {"type": "number"}},
            "required": ["a", "b"],
        },
        "fn": lambda a, b: a + b,            # 真正做菜的方法（函数）
    },
    "multiply": { ... },   # 同样的结构
    "weather":  { ... },   # 同样的结构
}
```

每个工具有三样东西：**名字描述、参数说明、真正的执行函数**。

> ⚠️ 注意这里的"分离"：`schema`（参数说明）是给 **LLM 看**的，让它知道"哦，add 工具需要两个数字 a 和 b"；`fn`（函数）是 **Server 自己执行**用的。LLM 永远看不到 `fn`，它只看 schema。**这就是"描述"和"执行"分离的具体体现。**

### ② 处理三种请求 —— 后厨只听得懂三句话

整个 MCP Server **只需要会处理三件事**，全在这一个函数里：

```python
def handle(method, params):
    if method == "initialize":      # ① 顾客进门打招呼
        return {"protocolVersion": "2024-11-05", "capabilities": {"tools": {}}}
    
    if method == "tools/list":      # ② 顾客要菜单
        return {"tools": [
            {"name": n, "description": t["desc"], "inputSchema": t["schema"]}
            for n, t in TOOLS.items()
        ]}
    
    if method == "tools/call":      # ③ 顾客点菜
        result = TOOLS[params["name"]]["fn"](**params.get("arguments", {}))
        return {"content": [{"type": "text", "text": str(result)}]}
```

| 方法 | 作用 | 餐厅类比 |
|------|------|---------|
| `initialize` | 握手，告知协议版本 | 进门打招呼 |
| `tools/list` | 返回所有工具的清单 | "给我看菜单" |
| `tools/call` | 执行指定的工具 | "点一道 add，a=3,b=5" |

就这三个！没有认证、没有登录、没有会话管理——**这就是最小可用的 MCP**。

### ③ HTTP 端点 —— 后厨的服务窗口

```python
class MCPHandler(BaseHTTPRequestHandler):
    def do_POST(self):
        msg = json.loads(self.rfile.read(...))   # 收到一封 JSON 信
        result = handle(msg["method"], msg.get("params", {}))  # 交给 handle 处理
        body = json.dumps({"jsonrpc": "2.0", "id": msg["id"], "result": result}).encode()
        self.send_response(200)                  # 把结果装进信封寄回去
        ...
```

**这和写一个最普通的 HTTP API 没有任何区别**：收 POST 请求的 body → 处理 → 返回 JSON。如果你写过 Flask / FastAPI，这段代码毫无门槛。MCP 用的传输方式叫 **Streamable HTTP**（MCP 规范推荐的），本质上就是普通的 HTTP 请求/响应。

---

## 第二部分：Agent（顾客）—— `nano_mcp_http_agent.py`

这个文件的核心信息在开头注释里就说了大实话：

> "就是第一篇 agent.py 的循环，工具来源从本地硬编码换成了 MCP Server。**没有什么 'MCP Client'——就是 run_agent，换了工具来源。**"

### ① 通信函数 —— 服务员跑腿，一个函数搞定

```python
def mcp_send(method, params={}):
    global _id; _id += 1
    resp = requests.post(
        SERVER_URL,
        json={"jsonrpc": "2.0", "id": _id, "method": method, "params": params},
    )
    return resp.json()["result"]
```

**整个 MCP 通信，就是一个 `requests.post()`**——发一个 JSON，收一个 JSON。所谓的 "JSON-RPC 2.0" 就是规定了这个 JSON 长什么样：带个 `method`（要干啥）、`params`（参数）、`id`（请求编号）。

### ② Agent 循环 —— 和第一篇一模一样

```python
def run_agent(task):
    mcp_send("initialize", ...)                              # 打招呼
    
    # 🔑 唯一变化①：工具不再硬编码，而是从 Server 要菜单
    tools = [ ...从 mcp_send("tools/list") 转换格式... ]
    
    messages = [系统提示, 用户任务]
    
    for _ in range(5):                                       # 循环最多5轮
        msg = LLM.chat(messages, tools=tools)                # 问大脑：用哪个工具？
        if 没有工具调用:
            return msg.content                                # 大脑答完了，结束
        for tc in msg.tool_calls:                            # 大脑要用工具
            # 🔑 唯一变化②：通过 HTTP 调用，而不是本地函数
            result = mcp_send("tools/call", {名字, 参数})
            把结果塞回 messages
```

**和第一篇 Agent 的循环结构一字不差**。唯一的变化就是这张表：

| | 第一篇的 Agent | 本文接入 MCP 的 Agent |
|---|---|---|
| 工具从哪来 | 代码里写死的字典 | `mcp_send("tools/list")` 从 Server 要 |
| 工具怎么执行 | `available_functions[fn](**args)` 本地调用 | `mcp_send("tools/call", ...)` 通过 HTTP |
| 循环结构 | 完全一样 | 完全一样 |

---

# 四、一次完整的对话流程（具体例子）

用户问 `"What is 3 + 5?"`，整个过程的通信：

```
用户: "What is 3 + 5?"

[Agent → Server] ① initialize（打招呼）
  发: {"method": "initialize", ...}
  收: {"protocolVersion": "2024-11-05", "capabilities": {...}}

[Agent → Server] ② tools/list（要菜单）
  发: {"method": "tools/list"}
  收: {"tools": [add, multiply, weather 三个工具的清单]}

[Agent] 把菜单转成 OpenAI 格式，交给 LLM 大脑
[LLM 思考] "3+5 要用 add 工具，参数 a=3, b=5"

[Agent → Server] ③ tools/call（点菜）
  发: {"method": "tools/call", "params": {"name": "add", "arguments": {"a": 3, "b": 5}}}
  收: {"content": [{"type": "text", "text": "8"}]}

[Agent] 把结果 "8" 喂回给 LLM
[LLM] 输出最终答案: "3 + 5 = 8"
```

**总共就三次 HTTP 请求**：`initialize → tools/list → tools/call`。整个过程结束。

---

# 五、⚠️ 一个最容易搞错的认知（Gotcha）

很多人刚学 MCP，会以为它是一个很复杂的新系统、有一个专门的 "MCP Client" 程序。**这是最大的误解。**

看代码注释里那句话：

> **"没有什么 'MCP Client'——就是第一篇的 run_agent，换了工具来源。"**

真相是：**MCP 没有给 Agent 带来任何新概念**。它只做了一件事——把 `available_functions[fn](**args)`（本地函数调用）换成了 `mcp_send("tools/call", ...)`（一次 HTTP 请求）。

```
以前：  本地函数调用        add(a=3, b=5)        → 直接拿到 8
现在：  跨网络 HTTP 调用    mcp_send("tools/call") → 通过网络拿到 8
```

**其他一切——Agent 循环、怎么问 LLM、怎么把结果喂回去——一个字都没变。** MCP 真正的价值不在于"让 AI 更聪明"，而在于：

1. **解耦**：工具可以跑在另一台机器上，Agent 不用关心它怎么实现
2. **标准化**：所有 AI 用同一套协议（USB-C），换工具不用改 Agent 代码
3. **可发现**：`tools/list` 让 Agent 动态发现有哪些工具可用，不用提前写死

换一个远程的 MCP Server？**改一行环境变量就行**：

```bash
export MCP_SERVER_URL="https://your-remote-server.com/mcp"
```

---

# 一句话总结

**MCP 的本质就是：Server 暴露工具、Agent 通过 JSON-RPC（`initialize`/`tools/list`/`tools/call` 三个方法）查询和调用工具、HTTP 是它们之间的管道。**

如果你记住了餐厅这个比喻——**后厨（Server）会做菜但不见客、顾客（Agent）不会做但会看菜单点菜、服务员（HTTP）在中间跑腿**——你就理解了 MCP 90% 的内容。剩下的 10% 只是 JSON 信封长什么样的细节。
