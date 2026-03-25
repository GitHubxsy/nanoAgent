"""
agent-preset.py — 用户预设 Agent + 主 Agent 委派

用户提前注册专家 Agent（前端/后端/测试），主 Agent 通过 delegate 工具
根据用户意图选择合适的 Agent 执行任务。已注册的 Agent 有持久记忆，
记得之前的对话。

用法:
python agent-preset.py "帮 TODO 应用加一个截止日期功能"
python agent-preset.py "帮我测试一下 TODO 应用"
python agent-preset.py   # 默认演示

环境变量:
OPENAI_API_KEY   (必须)
OPENAI_BASE_URL  (可选)
OPENAI_MODEL     (可选，默认 gpt-4o-mini)

GitHub: https://github.com/GitHubxsy/nanoAgent
"""

import os, sys, json
from openai import OpenAI

CLIENT = OpenAI(api_key=os.environ.get("OPENAI_API_KEY"), base_url=os.environ.get("OPENAI_BASE_URL"))
MODEL = os.environ.get("OPENAI_MODEL", "gpt-4o-mini")

# ============================================================
# 1. Agent：带独立工具集的持久智能体
# ============================================================

class Agent:
    def __init__(self, name, role, tools=None):
        self.name = name
        self.role = role
        self.tools = tools or []       # 每个 Agent 有自己的工具集
        self.messages = [{"role": "system", "content": f"You are {name}, a {role}. Be concise."}]
        self.inbox = []

    def receive(self, sender, message):
        self.inbox.append({"from": sender, "content": message})

    def chat(self, task):
        """处理收件箱 → 调用 LLM → 返回结果"""
        if self.inbox:
            inbox_text = "\n".join(f"[From {m['from']}]: {m['content']}" for m in self.inbox)
            self.messages.append({"role": "user", "content": f"Messages:\n{inbox_text}\n\nTask: {task}"})
            self.inbox.clear()
        else:
            self.messages.append({"role": "user", "content": task})

        reply = CLIENT.chat.completions.create(model=MODEL, messages=self.messages).choices[0].message.content
        self.messages.append({"role": "assistant", "content": reply})
        return reply


# ============================================================
# 2. AgentRegistry：用户注册和管理 Agent
# ============================================================

class AgentRegistry:
    def __init__(self):
        self.agents = {}

    def register(self, name, role, tools=None):
        self.agents[name] = Agent(name, role, tools)
        print(f"  [Registry] ✅ {name}")

    def unregister(self, name):
        del self.agents[name]

    def get(self, name):
        return self.agents.get(name)

    def list_agents(self):
        return [(n, a.role) for n, a in self.agents.items()]


# ============================================================
# 3. 主 Agent 委派：LLM 选择已注册 Agent
# ============================================================

def run_main_agent(task, registry, max_iterations=5):
    agent_names = [n for n, _ in registry.list_agents()]
    delegate_tool = {"type": "function", "function": {
        "name": "delegate",
        "description": f"Delegate a task to a specialist agent. Available: {', '.join(agent_names)}",
        "parameters": {"type": "object", "properties": {
            "agent_name": {"type": "string", "description": f"One of: {', '.join(agent_names)}"},
            "task":       {"type": "string", "description": "Task to delegate"}
        }, "required": ["agent_name", "task"]}
    }}
    messages = [
        {"role": "system", "content": "You are a main agent. Delegate tasks to specialist agents. Be concise."},
        {"role": "user", "content": task},
    ]
    for _ in range(max_iterations):
        msg = CLIENT.chat.completions.create(
            model=MODEL, messages=messages, tools=[delegate_tool]).choices[0].message
        messages.append(msg)
        if not msg.tool_calls:
            return msg.content
        for tc in msg.tool_calls:
            args = json.loads(tc.function.arguments)
            agent = registry.get(args["agent_name"])
            if agent:
                print(f"  [Main Agent] → {args['agent_name']}: {args['task']}")
                result = agent.chat(args["task"])
            else:
                result = f"Agent '{args['agent_name']}' not found. Available: {agent_names}"
            print(f"  [{args['agent_name']}] {result}")
            messages.append({"role": "tool", "tool_call_id": tc.id, "content": result})
    return "Max iterations reached"


# ============================================================
# 演示
# ============================================================

if __name__ == "__main__":
    # 1. 用户注册 Agent
    print("=== 注册 Agent ===")
    reg = AgentRegistry()
    reg.register("前端 Agent", "负责 TODO 应用的 React 前端", tools=["write_file", "read_file", "bash"])
    reg.register("后端 Agent", "负责 TODO 应用的 Python API",  tools=["write_file", "read_file", "bash"])
    reg.register("测试 Agent", "编写和运行测试用例",           tools=["read_file", "bash", "pytest"])

    # 2. 主 Agent 委派
    task = " ".join(sys.argv[1:]) if len(sys.argv) > 1 else "帮我给 TODO 应用加一个截止日期功能"
    print(f"\n=== 主 Agent 委派 ===")
    print(f"任务: {task}\n")
    print(run_main_agent(task, reg))

    # 3. 演示持久记忆（第二次任务，Agent 记得第一次的上下文）
    print(f"\n=== 持久记忆演示 ===")
    print(f"前端 Agent 消息数: {len(reg.get('前端 Agent').messages)}")
    print(run_main_agent("上次前端改了什么？帮我再加一个优先级功能", reg))
    print(f"前端 Agent 消息数: {len(reg.get('前端 Agent').messages)}（持久累积）")
