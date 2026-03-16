"""
agent-compact.py - 最简上下文压缩 Agent
基于 agent-essence.py (115行)，核心新增：当对话历史过长时，自动压缩成摘要

为什么需要压缩？
  Agent 每调用一次工具，messages 就多几条。10 轮循环后可能有 30+ 条消息。
  LLM 的 context window 是有限的（比如 8K/32K/128K tokens）。
  如果不压缩，messages 会撑爆窗口，API 报错，Agent 挂掉。

压缩的思路：
  当 messages 条数超过阈值时，把旧的对话历史交给 LLM 生成一段摘要，
  然后用 [system, 摘要, 最近几条消息] 替换掉原来的长历史。
  Agent 继续工作，就像人类"记住要点、忘掉细节"一样。

用法:
  python 06-compact/agent-compact.py "在当前目录下找到所有 Python 文件，统计每个文件的行数，按行数排序，结果写入 report.txt"
"""

import os
import json
import subprocess
import sys
from openai import OpenAI

client = OpenAI(
    api_key=os.environ.get("OPENAI_API_KEY"),
    base_url=os.environ.get("OPENAI_BASE_URL")
)

MODEL = os.environ.get("OPENAI_MODEL", "gpt-4o-mini")

# ==================== 工具（和 agent-essence.py 一样） ====================

tools = [
    {"type": "function", "function": {"name": "execute_bash", "description": "Execute a bash command on the system", "parameters": {"type": "object", "properties": {"command": {"type": "string", "description": "The bash command to execute"}}, "required": ["command"]}}},
    {"type": "function", "function": {"name": "read_file", "description": "Read contents of a file", "parameters": {"type": "object", "properties": {"path": {"type": "string", "description": "Path to the file"}}, "required": ["path"]}}},
    {"type": "function", "function": {"name": "write_file", "description": "Write content to a file", "parameters": {"type": "object", "properties": {"path": {"type": "string", "description": "Path to the file"}, "content": {"type": "string", "description": "Content to write"}}, "required": ["path", "content"]}}},
]

def execute_bash(command):
    try:
        result = subprocess.run(command, shell=True, capture_output=True, text=True, timeout=30)
        return result.stdout + result.stderr
    except Exception as e:
        return f"Error: {str(e)}"

def read_file(path):
    try:
        with open(path, 'r') as f:
            return f.read()
    except Exception as e:
        return f"Error: {str(e)}"

def write_file(path, content):
    try:
        with open(path, 'w') as f:
            f.write(content)
        return f"Successfully wrote to {path}"
    except Exception as e:
        return f"Error: {str(e)}"

available_functions = {
    "execute_bash": execute_bash,
    "read_file": read_file,
    "write_file": write_file
}

# ==================== 上下文压缩（核心新增） ====================
#
# 就这一个函数，约 30 行，实现了完整的压缩逻辑。
#
# 原理：
#   messages = [system, user, assistant, tool, assistant, tool, ...]
#                 ↓ 压缩后
#   messages = [system, 摘要(包含之前所有要点), 最近 N 条消息]

COMPACT_THRESHOLD = 20  # messages 超过这个数量就触发压缩
KEEP_RECENT = 6         # 压缩时保留最近几条消息（不压缩）

def compact_messages(messages):
    """
    当 messages 过长时，把旧消息压缩成一段摘要。

    压缩前: [system, msg1, msg2, ..., msg15, msg16, msg17, msg18, msg19, msg20]
    压缩后: [system, summary_of(msg1~msg14), msg15, msg16, msg17, msg18, msg19, msg20]
    """
    if len(messages) <= COMPACT_THRESHOLD:
        return messages  # 没超阈值，不压缩

    print(f"\n[Compact] messages 数量 ({len(messages)}) 超过阈值 ({COMPACT_THRESHOLD})，开始压缩...")

    system_msg = messages[0]            # system prompt 永远保留
    old_messages = messages[1:-KEEP_RECENT]  # 需要被压缩的旧消息
    recent_messages = messages[-KEEP_RECENT:]  # 最近的消息保留原样

    # 把旧消息拼成文本，交给 LLM 做摘要
    old_text = ""
    for msg in old_messages:
        role = msg.get("role", "unknown") if isinstance(msg, dict) else getattr(msg, "role", "unknown")
        content = msg.get("content", "") if isinstance(msg, dict) else getattr(msg, "content", "")
        if content:
            old_text += f"[{role}]: {content}\n"

    # 调用 LLM 生成摘要
    summary_response = client.chat.completions.create(
        model=MODEL,
        messages=[
            {"role": "system", "content": "Summarize the following conversation history into a concise summary. Keep all important facts, file paths, command results, and decisions. Be concise but don't lose critical details."},
            {"role": "user", "content": old_text}
        ]
    )
    summary = summary_response.choices[0].message.content

    print(f"[Compact] {len(old_messages)} 条旧消息 → 1 条摘要 (保留最近 {len(recent_messages)} 条)")
    print(f"[Compact] 压缩后 messages: {1 + 1 + len(recent_messages)} 条\n")

    # 重新组装：system + 摘要 + 最近消息
    return [
        system_msg,
        {"role": "user", "content": f"[Previous conversation summary]: {summary}"},
        {"role": "assistant", "content": "Understood. I have the context from our previous conversation. Let me continue."},
        *recent_messages
    ]

# ==================== Agent 核心循环（在 agent-essence.py 基础上加了压缩） ====================

def run_agent(user_message, max_iterations=30):
    messages = [
        {"role": "system", "content": "You are a helpful assistant that can interact with the system. Be concise."},
        {"role": "user", "content": user_message}
    ]

    for i in range(max_iterations):
        # ===== 新增：每轮循环前检查是否需要压缩 =====
        messages = compact_messages(messages)

        response = client.chat.completions.create(
            model=MODEL,
            messages=messages,
            tools=tools
        )

        message = response.choices[0].message
        messages.append(message)

        if not message.tool_calls:
            return message.content

        for tool_call in message.tool_calls:
            function_name = tool_call.function.name
            function_args = json.loads(tool_call.function.arguments)
            print(f"[Tool] {function_name}({json.dumps(function_args, ensure_ascii=False)[:80]})")
            function_response = available_functions[function_name](**function_args)
            messages.append({"role": "tool", "tool_call_id": tool_call.id, "content": function_response})

    return "Max iterations reached"

# ==================== 主入口 ====================

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python 06-compact/agent-compact.py 'your task'")
        print("\nExample:")
        print("  python 06-compact/agent-compact.py '找到所有 Python 文件，统计行数，按行数排序，写入 report.txt'")
        print()
        print("当对话超过 20 条消息时，自动压缩旧历史为摘要，Agent 可以持续工作不会撑爆 context window。")
        sys.exit(1)
    result = run_agent(" ".join(sys.argv[1:]))
    print(f"\n{result}")
