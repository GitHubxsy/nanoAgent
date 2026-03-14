"""
agent-teams.py - 最简多智能体团队协作

SubAgent 是一次性临时工：生成 → 干活 → 返回 → 消亡，无身份无记忆。
Teams 是真正的团队，需要三样东西:
  1. 持久智能体 —— Agent 有记忆，多次调用之间保持上下文
  2. 身份与生命周期 —— Agent 被创建、存活、可多次交互、最终解散
  3. 通信通道 —— Agent 之间可以互相发消息，而不只是贴公告板

用法:
  python agent-teams.py "创建一个 TODO 应用，包含 Python 后端和 HTML 前端"
"""

import os
import json
import subprocess
import sys
from datetime import datetime
from openai import OpenAI

client = OpenAI(
    api_key=os.environ.get("OPENAI_API_KEY"),
    base_url=os.environ.get("OPENAI_BASE_URL")
)

MODEL = os.environ.get("OPENAI_MODEL", "gpt-4o-mini")

# ==================== 工具 ====================

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

def bash(command):
    try:
        result = subprocess.run(command, shell=True, capture_output=True, text=True, timeout=30)
        return result.stdout + result.stderr
    except Exception as e:
        return f"Error: {str(e)}"

available_functions = {"read": read, "write": write, "edit": edit, "bash": bash}

tools = [
    {"type": "function", "function": {"name": "read", "description": "Read file with line numbers", "parameters": {"type": "object", "properties": {"path": {"type": "string"}, "offset": {"type": "integer"}, "limit": {"type": "integer"}}, "required": ["path"]}}},
    {"type": "function", "function": {"name": "write", "description": "Write content to file (creates dirs automatically)", "parameters": {"type": "object", "properties": {"path": {"type": "string"}, "content": {"type": "string"}}, "required": ["path", "content"]}}},
    {"type": "function", "function": {"name": "edit", "description": "Replace a unique string in file", "parameters": {"type": "object", "properties": {"path": {"type": "string"}, "old_string": {"type": "string"}, "new_string": {"type": "string"}}, "required": ["path", "old_string", "new_string"]}}},
    {"type": "function", "function": {"name": "bash", "description": "Run shell command", "parameters": {"type": "object", "properties": {"command": {"type": "string"}}, "required": ["command"]}}},
]

# ==================== 核心 1: 持久智能体（Agent 类） ====================
#
# 对比 SubAgent（一个函数调用就消亡），Agent 是一个有状态的对象:
#   - 有名字（name）和角色（role）—— 身份
#   - 有 messages 列表 —— 记忆，跨多次 chat() 调用持久保持
#   - 有 inbox —— 通信通道，接收其他 Agent 发来的消息

class Agent:
    def __init__(self, name, role):
        self.name = name
        self.role = role
        self.inbox = []  # 通信通道：其他 Agent 发来的消息
        self.messages = [  # 持久记忆：跨多次 chat() 保持
            {"role": "system", "content": f"You are {name}, a {role}. Be concise and focused."}
        ]
        print(f"  [创建] {name} ({role})")

    def receive(self, sender, message):
        """核心 3: 通信通道 —— 接收来自其他 Agent 的消息"""
        self.inbox.append({"from": sender, "content": message})

    def chat(self, task):
        """
        核心 1: 持久记忆 —— 每次 chat() 的对话都累积在 self.messages 中
        第二次 chat() 时，Agent 还记得第一次做了什么
        """
        # 如果 inbox 有新消息，先注入
        if self.inbox:
            mail = "\n".join(f"[来自 {m['from']}]: {m['content']}" for m in self.inbox)
            self.messages.append({"role": "user", "content": f"你收到了团队成员的消息:\n{mail}"})
            # 让 Agent 先消化这些消息
            resp = client.chat.completions.create(model=MODEL, messages=self.messages)
            self.messages.append(resp.choices[0].message)
            self.inbox.clear()

        # 执行本次任务
        self.messages.append({"role": "user", "content": task})

        for _ in range(10):
            response = client.chat.completions.create(model=MODEL, messages=self.messages, tools=tools)
            message = response.choices[0].message
            self.messages.append(message)

            if not message.tool_calls:
                print(f"  [{self.name}] → {message.content[:100]}...")
                return message.content

            for tc in message.tool_calls:
                fn = tc.function.name
                args = json.loads(tc.function.arguments)
                print(f"  [{self.name}] {fn}({json.dumps(args, ensure_ascii=False)[:60]})")
                result = available_functions.get(fn, lambda **_: "Tool not found")(**args)
                self.messages.append({"role": "tool", "tool_call_id": tc.id, "content": result})

        return "Max iterations reached"

# ==================== 核心 2: 身份与生命周期管理（Team 类） ====================
#
# Team 管理 Agent 的完整生命周期:
#   创建（hire）→ 存活（多次 chat + 互相通信）→ 解散（disband）

class Team:
    def __init__(self):
        self.agents = {}  # name → Agent

    def hire(self, name, role):
        """招募：创建一个持久 Agent"""
        agent = Agent(name, role)
        self.agents[name] = agent
        return agent

    def send(self, from_name, to_name, message):
        """核心 3: Agent 之间的通信通道"""
        if to_name not in self.agents:
            return f"Error: {to_name} not found"
        self.agents[to_name].receive(from_name, message)
        print(f"  [消息] {from_name} → {to_name}: {message[:60]}...")

    def broadcast(self, from_name, message):
        """广播：给团队所有其他人发消息"""
        for name, agent in self.agents.items():
            if name != from_name:
                agent.receive(from_name, message)
        print(f"  [广播] {from_name} → 全体: {message[:60]}...")

    def disband(self):
        """解散：所有 Agent 生命周期结束"""
        names = list(self.agents.keys())
        self.agents.clear()
        print(f"  [解散] 团队已解散 ({', '.join(names)})")

# ==================== 团队编排 ====================

def plan_team(task):
    """让 LLM 根据任务规划团队成员"""
    print(f"\n[PM] 分析任务，组建团队...")
    response = client.chat.completions.create(
        model=MODEL,
        messages=[
            {"role": "system", "content": """You are a project manager. Given a task, plan a team of 2-4 members.
Return JSON: {"team": [{"name": "alice", "role": "...", "task": "..."}]}
Rules: use lowercase english names, last member should be a reviewer, keep tasks concise."""},
            {"role": "user", "content": task}
        ],
        response_format={"type": "json_object"}
    )
    try:
        return json.loads(response.choices[0].message.content).get("team", [])
    except:
        return [{"name": "dev", "role": "developer", "task": task}]

def run_team(task):
    """
    完整的团队协作流程，展示三个核心能力:

    1. 持久记忆 —— 同一个 Agent 被多次 chat()，记得之前做过什么
    2. 身份生命周期 —— hire() 创建 → 多次交互 → disband() 解散
    3. 通信通道 —— Agent 之间通过 send()/broadcast() 传递信息
    """
    team = Team()

    # ---- 第 1 阶段：组建团队 ----
    members = plan_team(task)
    print(f"\n[团队] {len(members)} 人:")
    for i, m in enumerate(members, 1):
        print(f"  {i}. {m['name']} — {m['role']} → {m['task']}")

    print(f"\n{'='*60}")
    print("  第 1 阶段: 招募团队")
    print(f"{'='*60}")
    for m in members:
        team.hire(m["name"], m["role"])

    # ---- 第 2 阶段：逐个执行，每人干完把成果广播给全队 ----
    print(f"\n{'='*60}")
    print("  第 2 阶段: 协作开发")
    print(f"{'='*60}")

    results = {}
    for i, m in enumerate(members):
        print(f"\n{'─'*60}")
        print(f"  [{i+1}/{len(members)}] {m['name']} 开始工作")
        print(f"{'─'*60}")

        agent = team.agents[m["name"]]
        result = agent.chat(m["task"])
        results[m["name"]] = result

        # 干完活，把成果广播给团队其他人
        team.broadcast(m["name"], f"我完成了任务。摘要: {result[:200]}")

    # ---- 第 3 阶段（可选）：让最后一个成员做二次审查 ----
    # 这里展示"持久记忆"的价值：reviewer 已经通过 inbox 收到了所有人的成果
    # 再次 chat() 时，他还记得之前收到的所有广播消息
    last = members[-1]
    reviewer = team.agents[last["name"]]

    print(f"\n{'='*60}")
    print(f"  第 3 阶段: {last['name']} 做最终审查")
    print(f"{'='*60}")

    review = reviewer.chat("请根据你收到的所有团队成果，做一个最终的总结和审查。如有问题请指出。")
    results["final_review"] = review

    # ---- 解散 ----
    print(f"\n{'='*60}")
    print("  第 4 阶段: 解散团队")
    print(f"{'='*60}")
    team.disband()

    # ---- 输出 ----
    print(f"\n{'='*60}")
    print("  最终成果")
    print(f"{'='*60}\n")
    for name, result in results.items():
        print(f"[{name}]")
        print(f"  {result[:300]}\n")

    return results

# ==================== 主入口 ====================

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python agent-teams.py 'your task'")
        print("\nExample:")
        print("  python agent-teams.py '创建一个 TODO 应用，包含 Python 后端和 HTML 前端'")
        print()
        print("三大核心能力:")
        print("  1. 持久智能体 —— Agent 有记忆，多次交互保持上下文")
        print("  2. 身份与生命周期 —— 创建 → 协作 → 解散")
        print("  3. 通信通道 —— Agent 之间可以互相发消息")
        sys.exit(1)
    run_team(" ".join(sys.argv[1:]))
