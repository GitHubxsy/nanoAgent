"""
agent-compact.py - 最简上下文压缩 Agent
基于 agent-essence.py (100行)，核心新增：当对话历史过长时，自动压缩成摘要

为什么需要压缩？
  Agent 每调用一次工具，messages 就多几条。10 轮循环后可能有 30+ 条消息。
  LLM 的 context window 是有限的（比如 8K/32K/128K tokens）。
  如果不压缩，messages 会撑爆窗口，API 报错，Agent 挂掉。

压缩的思路：
  当 messages 条数超过阈值时，把旧的对话历史交给 LLM 生成一段摘要，
  然后用 [system, 摘要, 最近几条消息] 替换掉原来的长历史。
  Agent 继续工作，就像人类"记住要点、忘掉细节"一样。

用法:
  python agent/06-compact/agent-compact.py "请按步骤执行，不要合并成一个 shell 命令：先列出 agent 目录下的 Python 文件，再分别读取三个示例文件，最后写入 compact-demo-report.txt"
"""

import json
import subprocess
import sys
from pathlib import Path
import httpx
from openai import OpenAI

# Windows 控制台默认编码是 GBK/cp936，打印中文/emoji 会 UnicodeEncodeError。
# 强制 stdout/stderr 用 UTF-8；reconfigure 仅对真实文件流可用，故做容错。
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8")
    except (AttributeError, ValueError):
        pass  # 重定向 / 某些 IDE 捕获输出时不可用，跳过即可


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

MODEL = config["OPENAI_MODEL"]

# ==================== 工具（和 agent-essence.py 一样） ====================

tools = [
    {
        "type": "function",
        "function": {
            "name": "execute_bash",
            "description": "Execute a bash command on the system",
            "parameters": {
                "type": "object",
                "properties": {
                    "command": {
                        "type": "string",
                        "description": "The bash command to execute",
                    }
                },
                "required": ["command"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "read_file",
            "description": "Read contents of a file",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Path to the file"}
                },
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "write_file",
            "description": "Write content to a file",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Path to the file"},
                    "content": {"type": "string", "description": "Content to write"},
                },
                "required": ["path", "content"],
            },
        },
    },
]


def execute_bash(command):
    try:
        result = subprocess.run(
            command, shell=True, capture_output=True, text=True, timeout=30
        )
        return result.stdout + result.stderr
    except Exception as e:
        return f"Error: {str(e)}"


def read_file(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    except Exception as e:
        return f"Error: {str(e)}"


def write_file(path, content):
    try:
        with open(path, "w", encoding="utf-8") as f:
            f.write(content)
        return f"Successfully wrote to {path}"
    except Exception as e:
        return f"Error: {str(e)}"


available_functions = {
    "execute_bash": execute_bash,
    "read_file": read_file,
    "write_file": write_file,
}

# ==================== 上下文压缩（核心新增） ====================
#
# 核心是 compact_messages()；find_recent_start() 用来避免切断 tool 调用组。
#
# 原理：
#   messages = [system, user, assistant, tool, assistant, tool, ...]
#                 ↓ 压缩后
#   messages = [system, 摘要(包含之前所有要点), 最近 N 条消息]

COMPACT_THRESHOLD = 8  # 演示用低阈值：几轮工具调用后就能看到压缩
KEEP_RECENT = 4  # 至少保留最近几条消息；遇到 tool 调用组会向前扩展


def message_role(message):
    if isinstance(message, dict):
        return message.get("role", "unknown")
    return getattr(message, "role", "unknown")


def find_recent_start(messages):
    start = max(1, len(messages) - KEEP_RECENT)
    # 不要从 tool 消息中间切开；tool 必须紧跟触发它的 assistant tool_call。
    while start > 1 and message_role(messages[start]) == "tool":
        start -= 1
    return start


def compact_messages(messages):
    """
    当 messages 过长时，把旧消息压缩成一段摘要。

    压缩前: [system, msg1, msg2, msg3, msg4, msg5, msg6, msg7, msg8]
    压缩后: [system, summary_of(msg1~msg4), ack, msg5, msg6, msg7, msg8]
    """
    if len(messages) <= COMPACT_THRESHOLD:
        return messages  # 没超阈值，不压缩

    print(
        f"\n[Compact] messages 数量 ({len(messages)}) 超过阈值 ({COMPACT_THRESHOLD})，开始压缩..."
    )

    system_msg = messages[0]  # system prompt 永远保留
    recent_start = find_recent_start(messages)
    old_messages = messages[1:recent_start]  # 需要被压缩的旧消息
    recent_messages = messages[recent_start:]  # 最近的消息保留原样

    # 把旧消息拼成文本，交给 LLM 做摘要
    old_text = ""
    for msg in old_messages:
        role = message_role(msg)
        content = (
            msg.get("content", "")
            if isinstance(msg, dict)
            else getattr(msg, "content", "")
        )
        if content:
            old_text += f"[{role}]: {content}\n"

    # 调用 LLM 生成摘要
    summary_response = client.chat.completions.create(
        model=MODEL,
        messages=[
            {
                "role": "system",
                "content": "Summarize the following conversation history into a concise summary. Keep all important facts, file paths, command results, and decisions. Be concise but don't lose critical details.",
            },
            {"role": "user", "content": old_text},
        ],
    )
    summary = summary_response.choices[0].message.content

    print(
        f"[Compact] {len(old_messages)} 条旧消息 → 1 条摘要 (保留最近 {len(recent_messages)} 条)"
    )
    print(f"[Compact] 压缩后 messages: {1 + 2 + len(recent_messages)} 条\n")

    # 重新组装：system + 摘要 + 最近消息
    return [
        system_msg,
        {"role": "user", "content": f"[Previous conversation summary]: {summary}"},
        {
            "role": "assistant",
            "content": "Understood. I have the context from our previous conversation. Let me continue.",
        },
        *recent_messages,
    ]


# ==================== Agent 核心循环（在 agent-essence.py 基础上加了压缩） ====================


def run_agent(user_message, max_iterations=30):
    messages = [
        {
            "role": "system",
            "content": "You are a helpful assistant that can interact with the system. Be concise.",
        },
        {"role": "user", "content": user_message},
    ]

    for i in range(max_iterations):
        # ===== 新增：每轮循环前检查是否需要压缩 =====
        messages = compact_messages(messages)

        response = client.chat.completions.create(
            model=MODEL, messages=messages, tools=tools
        )

        message = response.choices[0].message
        messages.append(message)

        if not message.tool_calls:
            return message.content

        for tool_call in message.tool_calls:
            function_name = tool_call.function.name
            function_args = json.loads(tool_call.function.arguments)
            print(
                f"[Tool] {function_name}({json.dumps(function_args, ensure_ascii=False)[:80]})"
            )
            function_response = available_functions[function_name](**function_args)
            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": tool_call.id,
                    "content": function_response,
                }
            )

    return "Max iterations reached"


# ==================== 主入口 ====================

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python agent/06-compact/agent-compact.py 'your task'")
        print("\nExample:")
        print(
            "  python agent/06-compact/agent-compact.py '请按步骤执行，不要合并成一个 shell 命令：先列出 agent 目录下的 Python 文件，再分别读取三个示例文件，最后写入 compact-demo-report.txt'"
        )
        print()
        print(
            "演示阈值是 8 条消息，几轮工具调用后就会自动压缩旧历史为摘要。"
        )
        sys.exit(1)
    result = run_agent(" ".join(sys.argv[1:]))
    print(f"\n{result}")
