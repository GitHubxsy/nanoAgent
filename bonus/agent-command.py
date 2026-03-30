"""
agent-command.py — nanoAgent 番外篇：Command
演示 Agent Command 机制：在 run_agent 主循环之前加一层分流器，
匹配 / 开头的命令直接本地执行，不经过 LLM。

用法：
  python agent-command.py

命令：
  /help    - 显示帮助
  /clear   - 清空对话历史
  /model   - 切换模型（如 /model gpt-4o）
  /compact - 压缩对话历史
  /status  - 显示当前状态
"""

import os, sys, json
from openai import OpenAI

llm = OpenAI()
SYSTEM_PROMPT = "You are a helpful assistant with access to tools."

# ---- 工具定义（和第一篇一样） ----

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "bash",
            "description": "Execute a bash command and return its output",
            "parameters": {
                "type": "object",
                "properties": {
                    "command": {"type": "string", "description": "The bash command to execute"}
                },
                "required": ["command"]
            }
        }
    }
]

def bash(command):
    import subprocess
    result = subprocess.run(command, shell=True, capture_output=True, text=True)
    return result.stdout + result.stderr

available_functions = {"bash": bash}

# ==== Command 定义 ====

def cmd_help(args, messages):
    return """可用命令：
  /help    - 显示本帮助
  /clear   - 清空对话历史
  /model   - 切换模型（如 /model gpt-4o）
  /compact - 压缩对话历史
  /status  - 显示当前状态"""

def cmd_clear(args, messages):
    messages.clear()
    messages.append({"role": "system", "content": SYSTEM_PROMPT})
    return "对话已清空。"

def cmd_model(args, messages):
    if not args:
        return f"当前模型：{os.environ.get('OPENAI_MODEL', 'gpt-4o-mini')}"
    os.environ["OPENAI_MODEL"] = args[0]
    return f"模型已切换为：{args[0]}"

def cmd_status(args, messages):
    return f"消息数：{len(messages)}  |  模型：{os.environ.get('OPENAI_MODEL', 'gpt-4o-mini')}"

def cmd_compact(args, messages):
    if len(messages) <= 4:
        return "对话太短，无需压缩。"
    system_msg = messages[0]
    old_messages = messages[1:-2]
    recent = messages[-2:]
    summary = llm.chat.completions.create(
        model=os.environ.get("OPENAI_MODEL", "gpt-4o-mini"),
        messages=[
            {"role": "system", "content": "请用中文简洁总结以下对话的要点，保留关键事实和决策。"},
            {"role": "user", "content": str(old_messages)}
        ]
    ).choices[0].message.content
    messages.clear()
    messages.append(system_msg)
    messages.append({"role": "assistant", "content": f"[对话摘要] {summary}"})
    messages.extend(recent)
    return f"已压缩 {len(old_messages)} 条消息为摘要。当前消息数：{len(messages)}"

# ==== Command Router ====

COMMANDS = {
    "/help": cmd_help,
    "/clear": cmd_clear,
    "/model": cmd_model,
    "/status": cmd_status,
    "/compact": cmd_compact,
}

def handle_command(user_input, messages):
    parts = user_input.split()
    cmd, args = parts[0].lower(), parts[1:]
    if cmd in COMMANDS:
        return COMMANDS[cmd](args, messages)
    return None   # 不认识的 / 开头输入，交给 run_agent

# ==== 核心循环（第一篇的 run_agent） ====

def run_agent(messages):
    for _ in range(10):
        resp = llm.chat.completions.create(
            model=os.environ.get("OPENAI_MODEL", "gpt-4o-mini"),
            messages=messages, tools=TOOLS
        ).choices[0].message
        messages.append(resp)
        if not resp.tool_calls:
            return resp.content
        for tc in resp.tool_calls:
            fn_args = json.loads(tc.function.arguments)
            result = available_functions[tc.function.name](**fn_args)
            messages.append({"role": "tool", "tool_call_id": tc.id, "content": result})
    return "达到最大轮次。"

# ==== 主函数：先过 Command，再走 run_agent ====

def main():
    messages = [{"role": "system", "content": SYSTEM_PROMPT}]
    while True:
        try:
            user_input = input("\nYou: ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nBye!")
            break
        if not user_input:
            continue

        # Command 分流：匹配到就直接执行，不进 run_agent
        if user_input.startswith("/"):
            result = handle_command(user_input, messages)
            if result is not None:
                print(result)
                continue

        # 正常走 run_agent 主循环
        messages.append({"role": "user", "content": user_input})
        response = run_agent(messages)
        messages.append({"role": "assistant", "content": response})
        print(f"\nAgent: {response}")

if __name__ == "__main__":
    main()
