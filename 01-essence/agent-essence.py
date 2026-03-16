import os, json, subprocess, sys
from openai import OpenAI

client = OpenAI(api_key=os.environ.get("OPENAI_API_KEY"), base_url=os.environ.get("OPENAI_BASE_URL"))

def _tool(name, desc, **props):
    required = list(props.keys())
    return {"type": "function", "function": {"name": name, "description": desc,
            "parameters": {"type": "object", "properties": {k: {"type": "string"} for k in props}, "required": required}}}

tools = [
    _tool("execute_bash", "Execute a bash command", command="command to run"),
    _tool("read_file",    "Read a file",             path="file path"),
    _tool("write_file",   "Write to a file",         path="file path", content="file content"),
]


def execute_bash(command):
    r = subprocess.run(command, shell=True, capture_output=True, text=True)
    return r.stdout + r.stderr

def read_file(path):
    with open(path) as f: return f.read()

def write_file(path, content):
    with open(path, "w") as f: f.write(content)
    return f"Wrote to {path}"

functions = {"execute_bash": execute_bash, "read_file": read_file, "write_file": write_file}


def run_agent(user_message, max_iterations=5):
    messages = [
        {"role": "system", "content": "You are a helpful assistant. Be concise."},
        {"role": "user",   "content": user_message},
    ]
    for _ in range(max_iterations):
        response = client.chat.completions.create(
            model=os.environ.get("OPENAI_MODEL", "gpt-4o-mini"),
            messages=messages, tools=tools,
        )
        message = response.choices[0].message
        messages.append(message)
        if not message.tool_calls:
            return message.content
        for tc in message.tool_calls:
            name, args = tc.function.name, json.loads(tc.function.arguments)
            print(f"[Tool] {name}({args})")
            result = functions[name](**args) if name in functions else f"Error: Unknown tool '{name}'"
            messages.append({"role": "tool", "tool_call_id": tc.id, "content": result})
    return "Max iterations reached"


if __name__ == "__main__":
    task = " ".join(sys.argv[1:]) if len(sys.argv) > 1 else "Hello"
    print(run_agent(task))
