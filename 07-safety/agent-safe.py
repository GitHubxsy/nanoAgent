"""
agent-safe.py - 最简安全 Agent
基于 agent-essence.py (115行)，核心新增三道安全防线:

  1. 命令黑名单 —— 拦截危险命令（rm -rf、mkfs、dd 等）
  2. 用户确认 —— 高风险操作前必须人类确认
  3. 输出截断 —— 防止工具返回结果撑爆 context window

用法:
  python 07-safety/agent-safe.py "列出当前目录的文件"
  python 07-safety/agent-safe.py --auto "统计 Python 文件行数"   # 跳过确认（仅用于信任场景）
"""

import os
import json
import subprocess
import sys
import re
from openai import OpenAI

client = OpenAI(
    api_key=os.environ.get("OPENAI_API_KEY"),
    base_url=os.environ.get("OPENAI_BASE_URL")
)

MODEL = os.environ.get("OPENAI_MODEL", "gpt-4o-mini")
AUTO_APPROVE = False  # 是否跳过用户确认

# ==================== 安全防线 1: 命令黑名单 ====================
#
# 最简单粗暴但最有效的防线：直接拒绝已知的危险命令。
# 不需要 AI 判断，不需要复杂分析，正则匹配就够了。

DANGEROUS_PATTERNS = [
    r'\brm\s+(-[a-zA-Z]*f[a-zA-Z]*\s+|.*--no-preserve-root)',  # rm -rf, rm -f /
    r'\brm\s+(-[a-zA-Z]*r[a-zA-Z]*\s+)?/',                     # rm / 或 rm -r /
    r'\bmkfs\b',                    # 格式化磁盘
    r'\bdd\s+.*of\s*=\s*/dev/',     # 覆写磁盘
    r'>\s*/dev/sd[a-z]',            # 重定向到磁盘设备
    r'\bchmod\s+(-R\s+)?777\s+/',   # chmod 777 /
    r':\(\)\s*\{',                       # fork bomb :(){ :|:& };
    r'\bcurl\b.*\|\s*(ba)?sh',      # curl | bash（远程执行）
    r'\bwget\b.*\|\s*(ba)?sh',      # wget | bash
    r'\bshutdown\b',                # 关机
    r'\breboot\b',                  # 重启
    r'\binit\s+0',                  # 关机
]

def is_dangerous(command):
    """检查命令是否匹配黑名单"""
    for pattern in DANGEROUS_PATTERNS:
        if re.search(pattern, command):
            return True, pattern
    return False, None

# ==================== 安全防线 2: 用户确认 ====================
#
# 命令没有被黑名单拦截，不代表它是安全的。
# 所有 bash 命令在执行前都让用户过目确认。
# 类似 OpenClaw / Claude Code 中的 "Allow / Deny" 机制。

def ask_user_confirmation(tool_name, args):
    """执行前询问用户确认"""
    if AUTO_APPROVE:
        return True

    print(f"\n┌─ 确认执行 ─────────────────────────────")
    print(f"│ 工具: {tool_name}")
    for key, value in args.items():
        display = str(value)[:200]
        print(f"│ {key}: {display}")
    print(f"└────────────────────────────────────────")

    while True:
        answer = input("[Y]执行 / [N]跳过 / [Q]终止 Agent > ").strip().lower()
        if answer in ('y', 'yes', ''):
            return True
        elif answer in ('n', 'no'):
            return False
        elif answer in ('q', 'quit'):
            print("用户终止了 Agent。")
            sys.exit(0)
        else:
            print("请输入 Y/N/Q")

# ==================== 安全防线 3: 输出截断 ====================
#
# 工具返回的结果可能巨大（比如 cat 一个 10000 行的文件）。
# 不截断的话会迅速撑爆 context window（第六篇讲的问题）。
# 截断是压缩之外的另一道防线：从源头控制输入大小。

MAX_OUTPUT_LENGTH = 5000  # 字符数

def truncate_output(text):
    """超长输出截断，保留首尾"""
    if len(text) <= MAX_OUTPUT_LENGTH:
        return text
    half = MAX_OUTPUT_LENGTH // 2
    return (
        text[:half]
        + f"\n\n... [输出过长，已截断。原始 {len(text)} 字符，保留首尾各 {half} 字符] ...\n\n"
        + text[-half:]
    )

# ==================== 工具实现（加了安全检查） ====================

tools = [
    {"type": "function", "function": {"name": "execute_bash", "description": "Execute a bash command on the system", "parameters": {"type": "object", "properties": {"command": {"type": "string", "description": "The bash command to execute"}}, "required": ["command"]}}},
    {"type": "function", "function": {"name": "read_file", "description": "Read contents of a file", "parameters": {"type": "object", "properties": {"path": {"type": "string", "description": "Path to the file"}}, "required": ["path"]}}},
    {"type": "function", "function": {"name": "write_file", "description": "Write content to a file", "parameters": {"type": "object", "properties": {"path": {"type": "string", "description": "Path to the file"}, "content": {"type": "string", "description": "Content to write"}}, "required": ["path", "content"]}}},
]

def execute_bash(command):
    # 防线 1: 黑名单检查
    dangerous, pattern = is_dangerous(command)
    if dangerous:
        msg = f"🚫 命令被拦截（匹配危险模式: {pattern}）: {command}"
        print(f"  {msg}")
        return msg

    # 防线 2: 用户确认
    if not ask_user_confirmation("execute_bash", {"command": command}):
        return "用户跳过了此命令。"

    # 执行
    try:
        result = subprocess.run(command, shell=True, capture_output=True, text=True, timeout=30)
        output = result.stdout + result.stderr
    except subprocess.TimeoutExpired:
        output = "Error: 命令执行超时（30秒）"
    except Exception as e:
        output = f"Error: {str(e)}"

    # 防线 3: 输出截断
    return truncate_output(output)

def read_file(path):
    # 防线 2: 用户确认
    if not ask_user_confirmation("read_file", {"path": path}):
        return "用户跳过了此操作。"

    try:
        with open(path, 'r') as f:
            content = f.read()
    except Exception as e:
        return f"Error: {str(e)}"

    # 防线 3: 输出截断
    return truncate_output(content)

def write_file(path, content):
    # 防线 2: 用户确认
    if not ask_user_confirmation("write_file", {"path": path, "content": content}):
        return "用户跳过了此操作。"

    try:
        os.makedirs(os.path.dirname(path) if os.path.dirname(path) else '.', exist_ok=True)
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

# ==================== Agent 核心循环（和 agent-essence.py 一样） ====================

def run_agent(user_message, max_iterations=20):
    messages = [
        {"role": "system", "content": "You are a helpful assistant that can interact with the system. Be concise. If a command is blocked or skipped, try an alternative approach."},
        {"role": "user", "content": user_message}
    ]

    for _ in range(max_iterations):
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
            print(f"[Tool] {function_name}({json.dumps(function_args, ensure_ascii=False)[:80]})")
            function_response = available_functions[function_name](**function_args)
            messages.append({"role": "tool", "tool_call_id": tool_call.id, "content": function_response})

    return "Max iterations reached"

# ==================== 主入口 ====================

if __name__ == "__main__":
    AUTO_APPROVE = "--auto" in sys.argv
    if AUTO_APPROVE:
        sys.argv.remove("--auto")
        print("[模式] 自动确认已开启（跳过用户确认）\n")

    if len(sys.argv) < 2:
        print("Usage: python 07-safety/agent-safe.py [--auto] 'your task'")
        print("\nExample:")
        print("  python 07-safety/agent-safe.py '列出当前目录的文件'")
        print("  python 07-safety/agent-safe.py --auto '统计 Python 文件行数'")
        print()
        print("三道安全防线:")
        print("  1. 命令黑名单 —— 自动拦截 rm -rf、mkfs 等危险命令")
        print("  2. 用户确认   —— 每次执行前需要人类 Y/N 确认")
        print("  3. 输出截断   —— 超长输出自动截断，防止撑爆 context")
        sys.exit(1)

    result = run_agent(" ".join(sys.argv[1:]))
    print(f"\n{result}")
