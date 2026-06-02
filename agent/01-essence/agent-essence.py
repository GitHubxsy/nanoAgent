"""
Agent 最小实现 — 揭示 Agent 的本质：一个 LLM 驱动的循环。

核心循环：LLM 推理 → 工具调用 → 结果反馈 → 继续推理，直到得出最终答案。
这几十行代码包含了 Agent 的全部要素：
  - LLM（大脑）：负责理解和决策
  - Tools（手脚）：执行具体操作（执行命令、读写文件）
  - 循环（驱动力）：将 LLM 的决策转化为行动，再将行动结果反馈给 LLM
"""

import json
import subprocess
from pathlib import Path
import httpx
from openai import OpenAI


def load_config():
    """从项目根目录的 .agent/config.json 加载配置（API Key、模型等）。"""
    config_path = Path(__file__).resolve().parents[2] / ".agent" / "config.json"
    with open(config_path, "r", encoding="utf-8") as f:
        return json.load(f)


config = load_config()

# 初始化 OpenAI 兼容客户端（支持任何兼容 OpenAI 接口的模型服务）
client = OpenAI(
    api_key=config["OPENAI_API_KEY"],
    base_url=config["OPENAI_BASE_URL"],
    http_client=httpx.Client(verify=False),
)

# ── 工具定义（Tool Schema） ──────────────────────────────────────
# 告诉 LLM 它"能"调用哪些工具、每个工具需要什么参数。
# 这是 Agent 的"手脚"——LLM 本身只能输出文本，工具让它能真正地与世界交互。
tools = [
    {
        "type": "function",
        "function": {
            "name": "execute_bash",
            "description": "Execute a bash command",
            "parameters": {
                "type": "object",
                "properties": {"command": {"type": "string"}},
                "required": ["command"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "read_file",
            "description": "Read a file",
            "parameters": {
                "type": "object",
                "properties": {"path": {"type": "string"}},
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "write_file",
            "description": "Write to a file",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "content": {"type": "string"},
                },
                "required": ["path", "content"],
            },
        },
    },
]


# ── 工具实现 ──────────────────────────────────────────────────────
# 每个 Schema 背后的真实 Python 函数。LLM 决定"调用什么"，这些函数负责"真正去做"。

def execute_bash(command):
    """执行 shell 命令，返回 stdout + stderr。"""
    result = subprocess.run(command, shell=True, capture_output=True, text=True)
    return result.stdout + result.stderr


def read_file(path):
    """读取文件全部内容。"""
    with open(path, "r") as f:
        return f.read()


def write_file(path, content):
    """将内容写入文件。"""
    with open(path, "w") as f:
        f.write(content)
    return f"Wrote to {path}"


# 工具名 → 函数 的映射表，供 Agent 循环中按名称查找并调用
functions = {"execute_bash": execute_bash, "read_file": read_file, "write_file": write_file}


# ── Agent 核心循环 ────────────────────────────────────────────────
def run_agent(user_message, max_iterations=10):
    """
    Agent 的核心：一个 "推理 → 行动 → 观察" 的循环。

    每一轮迭代中：
      1. 将完整对话历史发给 LLM
      2. 如果 LLM 认为可以直接回答 → 返回文本结果，循环结束
      3. 如果 LLM 决定调用工具 → 执行工具，将结果追加到对话，进入下一轮

    这就是 Agent 与普通 Chatbot 的本质区别：
      Chatbot 是单轮问答，Agent 是多轮自主决策。
    """
    messages = [
        {"role": "system", "content": "You are a helpful assistant. Be concise."},
        {"role": "user", "content": user_message},
    ]

    for _ in range(max_iterations):
        # ① 调用 LLM：传入对话历史 + 工具定义，让模型决定下一步
        response = client.chat.completions.create(
            model=config["OPENAI_MODEL"],
            messages=messages,
            tools=tools,
        )
        message = response.choices[0].message
        messages.append(message)

        # ② 如果 LLM 没有请求调用工具，说明它已经得出最终答案
        if not message.tool_calls:
            return message.content

        # ③ LLM 请求了工具调用 → 逐个执行，将结果反馈回对话
        for tool_call in message.tool_calls:
            name = tool_call.function.name
            args = json.loads(tool_call.function.arguments)
            print(f"[Tool] {name}({args})")

            # 查找并执行对应的工具函数；未知工具返回错误信息
            if name not in functions:
                result = f"Error: Unknown tool '{name}'"
            else:
                result = functions[name](**args)

            # 将工具执行结果作为 tool 消息追加到对话历史
            messages.append({"role": "tool", "tool_call_id": tool_call.id, "content": result})

    # 安全阀：防止 Agent 陷入无限循环
    return "Max iterations reached"


if __name__ == "__main__":
    import sys

    task = " ".join(sys.argv[1:]) if len(sys.argv) > 1 else "Hello"
    print(run_agent(task))
