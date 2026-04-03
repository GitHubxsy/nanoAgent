"""
agent-stream.py - 流式输出版 Agent
基于 agent.py (115行)，核心新增:

  1. stream=True —— LLM 输出逐字打印
  2. 工具调用碎片拼接 —— 流式模式下 tool_calls 分散在多个 chunk 中
  3. Spinner Verbs —— 等待 LLM 首个 token 时随机显示动词
  4. 工具输出流式 —— subprocess.Popen 逐行打印 bash 输出
  5. 状态反馈 —— 每个阶段都有可见的提示

用法:
  python agent-stream.py "列出当前目录的文件"
"""

import os
import json
import subprocess
import sys
import random
import threading
from openai import OpenAI

client = OpenAI(
    api_key=os.environ.get("OPENAI_API_KEY"),
    base_url=os.environ.get("OPENAI_BASE_URL")
)

MODEL = os.environ.get("OPENAI_MODEL", "gpt-4o-mini")

# ==================== 工具定义（和 agent.py 完全一样）====================

tools = [
    {
        "type": "function",
        "function": {
            "name": "execute_bash",
            "description": "Execute a bash command on the system",
            "parameters": {
                "type": "object",
                "properties": {
                    "command": {"type": "string", "description": "The bash command to execute"}
                },
                "required": ["command"]
            }
        }
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
                "required": ["path"]
            }
        }
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
                    "content": {"type": "string", "description": "Content to write"}
                },
                "required": ["path", "content"]
            }
        }
    }
]

# ==================== 工具实现（execute_bash 改为流式）====================

def execute_bash(command):
    """流式执行 bash 命令，逐行打印输出"""
    print(f"  \033[90m$ {command}\033[0m", flush=True)
    output_lines = []
    try:
        process = subprocess.Popen(
            command, shell=True,
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True
        )
        for line in process.stdout:
            line = line.rstrip('\n')
            output_lines.append(line)
            print(f"    {line}", flush=True)
        process.wait()
        return '\n'.join(output_lines)
    except Exception as e:
        return f"Error: {str(e)}"

def read_file(path):
    try:
        with open(path, 'r') as f:
            content = f.read()
        print(f"  \033[90m({len(content)} 字符)\033[0m", flush=True)
        return content
    except Exception as e:
        return f"Error: {str(e)}"

def write_file(path, content):
    try:
        with open(path, 'w') as f:
            f.write(content)
        print(f"  \033[90m(已写入 {len(content)} 字符)\033[0m", flush=True)
        return f"Successfully wrote to {path}"
    except Exception as e:
        return f"Error: {str(e)}"

available_functions = {
    "execute_bash": execute_bash,
    "read_file": read_file,
    "write_file": write_file
}

# ==================== Spinner Verbs ====================

SPINNER_VERBS = [
    # 正经的
    "pondering", "contemplating", "reasoning", "analyzing",
    "orchestrating", "synthesizing", "deliberating", "evaluating",
    "investigating", "formulating", "computing", "processing",
    "examining", "deciphering", "assembling", "strategizing",
    "mapping", "surveying", "calibrating", "optimizing",
    # 搞怪的
    "discombobulating", "galumphing", "lollygagging",
    "flibbertigibbeting", "kerfuffling", "perambulating",
    "topsy-turvying", "hullabalooing", "cattywampusing",
    "wibble-wobbling", "shilly-shallying", "dilly-dallying",
]

class Spinner:
    """在等待 LLM 首个 token 时随机显示动词"""

    def __init__(self, interval=1.5):
        self.interval = interval
        self.running = False
        self.timer = None

    def _tick(self):
        if not self.running:
            return
        verb = random.choice(SPINNER_VERBS)
        sys.stderr.write(f"\r\033[K  \033[33m{verb}...\033[0m")
        sys.stderr.flush()
        self.timer = threading.Timer(self.interval, self._tick)
        self.timer.daemon = True
        self.timer.start()

    def start(self):
        self.running = True
        self._tick()

    def stop(self):
        self.running = False
        if self.timer:
            self.timer.cancel()
        sys.stderr.write("\r\033[K")
        sys.stderr.flush()

# ==================== 流式 chunk 收集 ====================

def collect_stream(stream, spinner):
    """
    从流式 chunk 中收集完整的文字内容和工具调用。

    流式模式下，tool_calls 分散在多个 chunk 里：
    - 函数名可能分成 "execute" + "_bash" 两个 chunk
    - 参数可能分成 '{"comma' + 'nd": "ls"}' 两个 chunk
    必须按 index 累积碎片，全部读完后拼成完整结构。
    """
    content = ""
    tool_calls = {}  # index → {id, name, arguments}
    first_chunk = True

    for chunk in stream:
        choice = chunk.choices[0] if chunk.choices else None
        if not choice:
            continue
        delta = choice.delta

        # 收到第一个有效 chunk 时停止 spinner
        if first_chunk and (delta.content or delta.tool_calls):
            spinner.stop()
            first_chunk = False

        # 累积文字，逐字打印
        if delta.content:
            content += delta.content
            print(delta.content, end="", flush=True)

        # 累积工具调用碎片
        if delta.tool_calls:
            for tc in delta.tool_calls:
                idx = tc.index
                if idx not in tool_calls:
                    tool_calls[idx] = {"id": "", "name": "", "arguments": ""}
                if tc.id:
                    tool_calls[idx]["id"] = tc.id
                if tc.function:
                    if tc.function.name:
                        tool_calls[idx]["name"] += tc.function.name
                    if tc.function.arguments:
                        tool_calls[idx]["arguments"] += tc.function.arguments

    # 如果 spinner 还在跑（比如 LLM 返回了空内容），确保停掉
    spinner.stop()

    if content:
        print()  # 换行

    # 把字典转成和同步模式兼容的列表结构
    completed_calls = [
        {
            "id": tool_calls[idx]["id"],
            "type": "function",
            "function": {
                "name": tool_calls[idx]["name"],
                "arguments": tool_calls[idx]["arguments"]
            }
        }
        for idx in sorted(tool_calls.keys())
    ]

    return content, completed_calls

# ==================== Agent 核心循环（流式版）====================

def run_agent(user_message, max_iterations=10):
    messages = [
        {"role": "system", "content": "You are a helpful assistant that can interact with the system. Be concise."},
        {"role": "user", "content": user_message}
    ]

    for i in range(max_iterations):
        print(f"\n\033[36m[轮次 {i+1}]\033[0m", flush=True)

        # 启动 spinner，等待 LLM 响应
        spinner = Spinner()
        spinner.start()

        # 流式调用 LLM
        stream = client.chat.completions.create(
            model=MODEL,
            messages=messages,
            tools=tools,
            stream=True
        )

        # 收集流式结果（内部会停止 spinner 并逐字打印）
        content, tool_calls = collect_stream(stream, spinner)

        # 把 LLM 的回复加入 messages
        assistant_message = {"role": "assistant", "content": content}
        if tool_calls:
            assistant_message["tool_calls"] = tool_calls
        messages.append(assistant_message)

        # 没有工具调用 → 任务结束
        if not tool_calls:
            return content

        # 执行工具调用
        for tc in tool_calls:
            function_name = tc["function"]["name"]
            function_args = json.loads(tc["function"]["arguments"])
            print(f"  \033[32m[工具] {function_name}\033[0m", flush=True)
            print(f"  \033[90m[执行中...]\033[0m", flush=True)

            function_response = available_functions[function_name](**function_args)

            print(f"  \033[90m[完成] 返回 {len(function_response)} 字符\033[0m", flush=True)

            messages.append({
                "role": "tool",
                "tool_call_id": tc["id"],
                "content": function_response
            })

    return "Max iterations reached"

# ==================== 入口 ====================

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python agent-stream.py 'your task here'")
        sys.exit(1)

    task = " ".join(sys.argv[1:])
    result = run_agent(task)
    print(f"\n{result}")
