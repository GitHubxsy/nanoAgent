"""
agent-full.py - 七篇合一的完整 Agent

集成了「从零开始理解 Agent」系列全部七篇的核心功能:
  第一篇: 工具 + 循环 (read/write/edit/glob/grep/bash)
  第二篇: 记忆 (agent_memory.md 持久化)
  第三篇: Rules (.agent/rules/*.md) + Skills (.agent/skills/*.json) + MCP (.agent/mcp.json)
  第四篇: SubAgent (一次性子智能体)
  第五篇: Teams (持久多智能体协作)
  第六篇: 上下文压缩 (compact_messages)
  第七篇: 安全防线 (黑名单 + 用户确认 + 输出截断 + Hook 管道)

用法:
  python agent-full.py "你的任务"
  python agent-full.py --auto "你的任务"      # 跳过用户确认
  python agent-full.py --team "你的任务"       # 使用多智能体团队模式
"""

import os
import json
import subprocess
import sys
import re
import glob as glob_module
from datetime import datetime
from pathlib import Path
from openai import OpenAI

client = OpenAI(
    api_key=os.environ.get("OPENAI_API_KEY"),
    base_url=os.environ.get("OPENAI_BASE_URL")
)

MODEL = os.environ.get("OPENAI_MODEL", "gpt-4o-mini")
AUTO_APPROVE = False

# ======================== 第七篇: 安全防线 ========================

# --- 防线 1: 命令黑名单 ---

DANGEROUS_PATTERNS = [
    r'\brm\s+(-[a-zA-Z]*f[a-zA-Z]*\s+|.*--no-preserve-root)',
    r'\brm\s+(-[a-zA-Z]*r[a-zA-Z]*\s+)?/',
    r'\bmkfs\b',
    r'\bdd\s+.*of\s*=\s*/dev/',
    r'>\s*/dev/sd[a-z]',
    r'\bchmod\s+(-R\s+)?777\s+/',
    r':\(\)\s*\{',
    r'\bcurl\b.*\|\s*(ba)?sh',
    r'\bwget\b.*\|\s*(ba)?sh',
    r'\bshutdown\b',
    r'\breboot\b',
]

def is_dangerous(command):
    for pattern in DANGEROUS_PATTERNS:
        if re.search(pattern, command):
            return True, pattern
    return False, None

# --- 防线 2: 用户确认 ---

def ask_user_confirmation(tool_name, args):
    if AUTO_APPROVE:
        return True
    print(f"\n┌─ 确认执行 ─────────────────────────────")
    print(f"│ 工具: {tool_name}")
    for key, value in args.items():
        print(f"│ {key}: {str(value)[:200]}")
    print(f"└────────────────────────────────────────")
    while True:
        answer = input("[Y]执行 / [N]跳过 / [Q]终止 > ").strip().lower()
        if answer in ('y', 'yes', ''):
            return True
        elif answer in ('n', 'no'):
            return False
        elif answer in ('q', 'quit'):
            sys.exit(0)

# --- 防线 3: 输出截断 ---

MAX_OUTPUT_LENGTH = 5000

def truncate_output(text):
    if len(text) <= MAX_OUTPUT_LENGTH:
        return text
    half = MAX_OUTPUT_LENGTH // 2
    return text[:half] + f"\n\n... [已截断，原始 {len(text)} 字符] ...\n\n" + text[-half:]

# --- 第七篇进化: Hook 管道 ---

def hook_blacklist(tool_name, args):
    if tool_name == "bash":
        dangerous, pattern = is_dangerous(args.get("command", ""))
        if dangerous:
            return True, f"🚫 命令被拦截（匹配: {pattern}）"
    return False, None

def hook_confirm(tool_name, args):
    if not ask_user_confirmation(tool_name, args):
        return True, "用户跳过了此操作。"
    return False, None

def hook_truncate(tool_name, result):
    return truncate_output(result)

before_hooks = [hook_blacklist, hook_confirm]
after_hooks = [hook_truncate]

def execute_with_hooks(tool_name, args, func):
    """通用工具执行: before hooks → 执行 → after hooks"""
    for hook in before_hooks:
        blocked, msg = hook(tool_name, args)
        if blocked:
            print(f"  {msg}")
            return msg
    result = func(**args)
    for hook in after_hooks:
        result = hook(tool_name, result)
    return result

# ======================== 第一篇 + 第三篇: 工具 ========================

def read(path, offset=None, limit=None):
    try:
        with open(path, 'r') as f:
            lines = f.readlines()
        start = offset if offset else 0
        end = start + limit if limit else len(lines)
        return ''.join(f"{i+1:4d} {line}" for i, line in enumerate(lines[start:end], start))
    except Exception as e:
        return f"Error: {str(e)}"

def write(path, content):
    try:
        os.makedirs(os.path.dirname(path) if os.path.dirname(path) else '.', exist_ok=True)
        with open(path, 'w') as f:
            f.write(content)
        return f"Successfully wrote to {path}"
    except Exception as e:
        return f"Error: {str(e)}"

def edit(path, old_string, new_string):
    try:
        with open(path, 'r') as f:
            content = f.read()
        if content.count(old_string) != 1:
            return f"Error: old_string must appear exactly once (found {content.count(old_string)})"
        with open(path, 'w') as f:
            f.write(content.replace(old_string, new_string))
        return f"Successfully edited {path}"
    except Exception as e:
        return f"Error: {str(e)}"

def grep(pattern, path="."):
    try:
        result = subprocess.run(f"grep -rn '{pattern}' {path}", shell=True, capture_output=True, text=True, timeout=30)
        return result.stdout if result.stdout else "No matches found"
    except Exception as e:
        return f"Error: {str(e)}"

def glob(pattern):
    try:
        files = sorted(glob_module.glob(pattern, recursive=True), key=lambda x: os.path.getmtime(x), reverse=True)
        return '\n'.join(files) if files else "No files found"
    except Exception as e:
        return f"Error: {str(e)}"

def bash(command):
    try:
        result = subprocess.run(command, shell=True, capture_output=True, text=True, timeout=30)
        return result.stdout + result.stderr
    except subprocess.TimeoutExpired:
        return "Error: 命令执行超时（30秒）"
    except Exception as e:
        return f"Error: {str(e)}"

# ======================== 第四篇: SubAgent ========================

def subagent(role, task):
    """一次性子智能体: 生成 → 干活 → 返回 → 消亡"""
    print(f"\n{'='*50}")
    print(f"[SubAgent:{role}] 开始: {task}")
    print(f"{'='*50}")
    sub_messages = [
        {"role": "system", "content": f"You are a {role}. Be concise and focused. Only do what is asked."},
        {"role": "user", "content": task}
    ]
    sub_tools = [t for t in base_tools if t["function"]["name"] != "subagent"]
    for _ in range(10):
        response = client.chat.completions.create(model=MODEL, messages=sub_messages, tools=sub_tools)
        message = response.choices[0].message
        sub_messages.append(message)
        if not message.tool_calls:
            print(f"[SubAgent:{role}] 完成\n")
            return message.content
        for tc in message.tool_calls:
            fn = tc.function.name
            args = json.loads(tc.function.arguments)
            print(f"  [SubAgent:{role}] {fn}({json.dumps(args, ensure_ascii=False)[:80]})")
            result = execute_with_hooks(fn, args, raw_functions[fn])
            sub_messages.append({"role": "tool", "tool_call_id": tc.id, "content": result})
    return "SubAgent: max iterations reached"

# --- 工具注册 ---

raw_functions = {
    "read": read, "write": write, "edit": edit,
    "grep": grep, "glob": glob, "bash": bash,
    "subagent": subagent,
}

base_tools = [
    {"type": "function", "function": {"name": "read", "description": "Read file with line numbers", "parameters": {"type": "object", "properties": {"path": {"type": "string"}, "offset": {"type": "integer"}, "limit": {"type": "integer"}}, "required": ["path"]}}},
    {"type": "function", "function": {"name": "write", "description": "Write content to file", "parameters": {"type": "object", "properties": {"path": {"type": "string"}, "content": {"type": "string"}}, "required": ["path", "content"]}}},
    {"type": "function", "function": {"name": "edit", "description": "Replace a unique string in file", "parameters": {"type": "object", "properties": {"path": {"type": "string"}, "old_string": {"type": "string"}, "new_string": {"type": "string"}}, "required": ["path", "old_string", "new_string"]}}},
    {"type": "function", "function": {"name": "grep", "description": "Search files for pattern", "parameters": {"type": "object", "properties": {"pattern": {"type": "string"}, "path": {"type": "string"}}, "required": ["pattern"]}}},
    {"type": "function", "function": {"name": "glob", "description": "Find files by pattern", "parameters": {"type": "object", "properties": {"pattern": {"type": "string"}}, "required": ["pattern"]}}},
    {"type": "function", "function": {"name": "bash", "description": "Run shell command", "parameters": {"type": "object", "properties": {"command": {"type": "string"}}, "required": ["command"]}}},
    {"type": "function", "function": {"name": "subagent", "description": "Delegate a task to a specialized sub-agent with its own role and context. Use when a task benefits from focused expertise.", "parameters": {"type": "object", "properties": {"role": {"type": "string", "description": "e.g. 'Python backend developer'"}, "task": {"type": "string", "description": "The specific task to delegate"}}, "required": ["role", "task"]}}},
]

# ======================== 第三篇: Rules + Skills + MCP ========================

RULES_DIR = ".agent/rules"
SKILLS_DIR = ".agent/skills"
MCP_CONFIG = ".agent/mcp.json"

def load_rules():
    if not os.path.exists(RULES_DIR):
        return ""
    try:
        rules = []
        for f in Path(RULES_DIR).glob("*.md"):
            with open(f, 'r') as fh:
                rules.append(f"# {f.stem}\n{fh.read()}")
        return "\n\n".join(rules)
    except:
        return ""

def load_skills():
    if not os.path.exists(SKILLS_DIR):
        return []
    try:
        skills = []
        for f in Path(SKILLS_DIR).glob("*.json"):
            with open(f, 'r') as fh:
                skills.append(json.load(fh))
        return skills
    except:
        return []

def load_mcp_tools():
    if not os.path.exists(MCP_CONFIG):
        return []
    try:
        with open(MCP_CONFIG, 'r') as f:
            config = json.load(f)
        mcp_tools = []
        for name, srv in config.get("mcpServers", {}).items():
            if srv.get("disabled"):
                continue
            for tool in srv.get("tools", []):
                mcp_tools.append({"type": "function", "function": tool})
        return mcp_tools
    except:
        return []

# ======================== 第二篇: 记忆 ========================

MEMORY_FILE = "agent_memory.md"

def load_memory():
    if not os.path.exists(MEMORY_FILE):
        return ""
    try:
        with open(MEMORY_FILE, 'r') as f:
            lines = f.read().split('\n')
        return '\n'.join(lines[-50:]) if len(lines) > 50 else '\n'.join(lines)
    except:
        return ""

def save_memory(task, result):
    try:
        with open(MEMORY_FILE, 'a') as f:
            f.write(f"\n## {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n**Task:** {task}\n**Result:** {result[:500]}\n")
    except:
        pass

# ======================== 第六篇: 上下文压缩 ========================

COMPACT_THRESHOLD = 20
KEEP_RECENT = 6

def compact_messages(messages):
    if len(messages) <= COMPACT_THRESHOLD:
        return messages
    print(f"\n[Compact] {len(messages)} 条消息 → 压缩中...")
    system_msg = messages[0]
    old_messages = messages[1:-KEEP_RECENT]
    recent_messages = messages[-KEEP_RECENT:]
    old_text = ""
    for msg in old_messages:
        role = msg.get("role", "unknown") if isinstance(msg, dict) else getattr(msg, "role", "unknown")
        content = msg.get("content", "") if isinstance(msg, dict) else getattr(msg, "content", "")
        if content:
            old_text += f"[{role}]: {content}\n"
    summary_resp = client.chat.completions.create(
        model=MODEL,
        messages=[
            {"role": "system", "content": "Summarize this conversation. Keep important facts, paths, results, and decisions. Be concise."},
            {"role": "user", "content": old_text}
        ]
    )
    summary = summary_resp.choices[0].message.content
    print(f"[Compact] {len(old_messages)} 条旧消息 → 1 条摘要 (保留最近 {len(recent_messages)} 条)\n")
    return [
        system_msg,
        {"role": "user", "content": f"[Previous conversation summary]: {summary}"},
        {"role": "assistant", "content": "Understood. I have the context. Let me continue."},
        *recent_messages
    ]

# ======================== 第五篇: Teams ========================

class Agent:
    """持久智能体: 有名字、有记忆、有收件箱"""
    def __init__(self, name, role):
        self.name = name
        self.role = role
        self.inbox = []
        self.messages = [{"role": "system", "content": f"You are {name}, a {role}. Be concise and focused."}]
        print(f"  [创建] {name} ({role})")

    def receive(self, sender, message):
        self.inbox.append({"from": sender, "content": message})

    def chat(self, task):
        if self.inbox:
            mail = "\n".join(f"[来自 {m['from']}]: {m['content']}" for m in self.inbox)
            self.messages.append({"role": "user", "content": f"你收到了团队消息:\n{mail}"})
            resp = client.chat.completions.create(model=MODEL, messages=self.messages)
            self.messages.append(resp.choices[0].message)
            self.inbox.clear()
        self.messages.append({"role": "user", "content": task})
        agent_tools = [t for t in base_tools if t["function"]["name"] != "subagent"]
        for _ in range(10):
            response = client.chat.completions.create(model=MODEL, messages=self.messages, tools=agent_tools)
            message = response.choices[0].message
            self.messages.append(message)
            if not message.tool_calls:
                print(f"  [{self.name}] → {message.content[:100]}...")
                return message.content
            for tc in message.tool_calls:
                fn = tc.function.name
                args = json.loads(tc.function.arguments)
                print(f"  [{self.name}] {fn}({json.dumps(args, ensure_ascii=False)[:60]})")
                result = execute_with_hooks(fn, args, raw_functions[fn])
                self.messages.append({"role": "tool", "tool_call_id": tc.id, "content": result})
        return "Max iterations reached"

class Team:
    """团队: 管理生命周期与通信"""
    def __init__(self):
        self.agents = {}
    def hire(self, name, role):
        agent = Agent(name, role)
        self.agents[name] = agent
        return agent
    def send(self, from_name, to_name, message):
        self.agents[to_name].receive(from_name, message)
    def broadcast(self, from_name, message):
        for name, agent in self.agents.items():
            if name != from_name:
                agent.receive(from_name, message)
        print(f"  [广播] {from_name} → 全体: {message[:60]}...")
    def disband(self):
        names = list(self.agents.keys())
        self.agents.clear()
        print(f"  [解散] 团队已解散 ({', '.join(names)})")

# ======================== Agent 核心循环 ========================

def run_agent(messages, all_tools, max_iterations=30):
    for _ in range(max_iterations):
        messages = compact_messages(messages)
        response = client.chat.completions.create(model=MODEL, messages=messages, tools=all_tools)
        message = response.choices[0].message
        messages.append(message)
        if not message.tool_calls:
            return message.content, messages
        for tc in message.tool_calls:
            fn = tc.function.name
            args = json.loads(tc.function.arguments)
            print(f"[Tool] {fn}({json.dumps(args, ensure_ascii=False)[:100]})")
            if fn in raw_functions:
                result = execute_with_hooks(fn, args, raw_functions[fn])
            else:
                result = f"Tool {fn} not implemented"
            messages.append({"role": "tool", "tool_call_id": tc.id, "content": result})
    return "Max iterations reached", messages

# ======================== 主编排 ========================

def build_system_prompt():
    """构建 system prompt: 基础指令 + Rules + Skills + Memory"""
    parts = ["You are a helpful assistant. You can do tasks yourself or delegate to sub-agents. Be concise."]
    rules = load_rules()
    if rules:
        parts.append(f"\n# Rules\n{rules}")
        print(f"[Init] Rules loaded")
    skills = load_skills()
    if skills:
        parts.append("\n# Skills\n" + "\n".join(f"- {s['name']}: {s.get('description','')}" for s in skills))
        print(f"[Init] {len(skills)} skills loaded")
    memory = load_memory()
    if memory:
        parts.append(f"\n# Previous Context\n{memory}")
    return "\n".join(parts)

def run_single(task):
    """单 Agent 模式（第一~四、六、七篇的能力）"""
    mcp_tools = load_mcp_tools()
    if mcp_tools:
        print(f"[Init] {len(mcp_tools)} MCP tools loaded")
    all_tools = base_tools + mcp_tools

    messages = [
        {"role": "system", "content": build_system_prompt()},
        {"role": "user", "content": task}
    ]
    result, _ = run_agent(messages, all_tools)
    print(f"\n{result}")
    save_memory(task, result)
    return result

def run_team_mode(task):
    """多智能体团队模式（第五篇的能力）"""
    team = Team()
    print(f"\n[PM] 分析任务，组建团队...")
    resp = client.chat.completions.create(
        model=MODEL,
        messages=[
            {"role": "system", "content": 'You are a PM. Plan a team of 2-4 members.\nReturn JSON: {"team": [{"name": "alice", "role": "...", "task": "..."}]}\nLast member should be a reviewer.'},
            {"role": "user", "content": task}
        ],
        response_format={"type": "json_object"}
    )
    try:
        members = json.loads(resp.choices[0].message.content).get("team", [])
    except:
        members = [{"name": "dev", "role": "developer", "task": task}]

    print(f"[团队] {len(members)} 人:")
    for i, m in enumerate(members, 1):
        print(f"  {i}. {m['name']} — {m['role']} → {m['task']}")

    for m in members:
        team.hire(m["name"], m["role"])

    results = {}
    for i, m in enumerate(members):
        print(f"\n{'─'*50}\n  [{i+1}/{len(members)}] {m['name']} 开始工作\n{'─'*50}")
        result = team.agents[m["name"]].chat(m["task"])
        results[m["name"]] = result
        team.broadcast(m["name"], f"完成。摘要: {result[:200]}")

    last = members[-1]
    print(f"\n{'='*50}\n  {last['name']} 做最终审查\n{'='*50}")
    review = team.agents[last["name"]].chat("请根据团队成果做最终审查。")
    results["final_review"] = review

    team.disband()
    save_memory(task, str(results)[:500])

    print(f"\n{'='*50}\n  最终成果\n{'='*50}\n")
    for name, r in results.items():
        print(f"[{name}]\n  {r[:300]}\n")
    return results

# ======================== 入口 ========================

if __name__ == "__main__":
    AUTO_APPROVE = "--auto" in sys.argv
    team_mode = "--team" in sys.argv
    for flag in ("--auto", "--team"):
        if flag in sys.argv:
            sys.argv.remove(flag)

    if len(sys.argv) < 2:
        print("Usage: python agent-full.py [--auto] [--team] 'your task'")
        print()
        print("Modes:")
        print("  (default)  单 Agent: 工具+记忆+Rules+Skills+MCP+SubAgent+压缩+安全")
        print("  --team     多智能体团队: 自动组建团队协作")
        print("  --auto     跳过用户确认（仅用于信任环境）")
        print()
        print("Example:")
        print("  python agent-full.py '列出当前目录的 Python 文件并统计行数'")
        print("  python agent-full.py --team '创建一个 TODO 应用，包含后端和前端'")
        sys.exit(1)

    task = " ".join(sys.argv[1:])
    if team_mode:
        run_team_mode(task)
    else:
        run_single(task)
