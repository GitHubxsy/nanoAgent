import json
import subprocess
import sys
import httpx
from pathlib import Path
from datetime import datetime
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

MEMORY_FILE = "agent_memory.md"

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


def execute_bash(command):
    result = subprocess.run(command, shell=True, capture_output=True, text=True)
    return result.stdout + result.stderr


def read_file(path):
    with open(path, "r", encoding="utf-8") as f:
        return f.read()


def write_file(path, content):
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)
    return f"Wrote to {path}"


functions = {"execute_bash": execute_bash, "read_file": read_file, "write_file": write_file}


def load_memory():
    if not Path(MEMORY_FILE).exists():
        return ""
    with open(MEMORY_FILE, "r", encoding="utf-8") as f:
        lines = f.read().splitlines()
    return "\n".join(lines[-50:])


def save_memory(task, result):
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    entry = f"\n## {timestamp}\n**Task:** {task}\n**Result:** {result}\n"
    with open(MEMORY_FILE, "a", encoding="utf-8") as f:
        f.write(entry)
    print(f"[Memory] Saved to {MEMORY_FILE}")


def build_messages(user_message):
    system_prompt = "You are a helpful assistant. Be concise."
    memory = load_memory()
    if memory:
        print(f"[Memory] Loaded {MEMORY_FILE}")
        system_prompt += f"\n\nPrevious context:\n{memory}"
    return [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_message},
    ]


def run_agent(user_message, max_iterations=20):
    messages = build_messages(user_message)
    for _ in range(max_iterations):
        response = client.chat.completions.create(
            model=config["OPENAI_MODEL"],
            messages=messages,
            tools=tools,
        )
        message = response.choices[0].message
        messages.append(message)
        if not message.tool_calls:
            save_memory(user_message, message.content)
            return message.content
        for tool_call in message.tool_calls:
            name = tool_call.function.name
            args = json.loads(tool_call.function.arguments)
            print(f"[Tool] {name}({args})")
            if name not in functions:
                result = f"Error: Unknown tool '{name}'"
            else:
                result = functions[name](**args)
            messages.append(
                {"role": "tool", "tool_call_id": tool_call.id, "content": result}
            )
    result = "Max iterations reached"
    save_memory(user_message, result)
    return result


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python3 agent/02-memory/agent-memory.py 'your task here'")
        sys.exit(1)
    task = " ".join(sys.argv[1:])
    print(run_agent(task))
