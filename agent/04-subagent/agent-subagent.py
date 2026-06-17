"""
第 04 章: SubAgent 委托模式
==========================
agent-subagent.py - 最简 SubAgent 实现

核心思路：
  - subagent 在主 Agent 眼里就是一个「普通工具」，调用时却会在内部启动一条
    全新的、独立的 Agent 循环（拥有专属角色 + 独立上下文），完成后把结果
    作为工具返回值交还给主 Agent。
  - 主 Agent 因此升级为「编排者（orchestrator）」：自己能动手，也能把需要
    专业能力的子任务委派给不同角色的子代理。
  - 防递归：子代理的工具集里剔除了 subagent 自身，避免无限套娃。

本章在前几章（工具循环 / 记忆 / 规则与技能）之上只新增一个概念——
「把一个完整的小 Agent 当作工具暴露出去」。

运行方式：
  python agent/04-subagent/agent-subagent.py "你的任务"
  python agent/04-subagent/agent-subagent.py \
    "不要直接完成任务。请调用 subagent 工具两次，两个子代理都不要读写文件：1）role=Python API 设计师..."
"""

import os
import json
import subprocess
from pathlib import Path
import sys
import glob as glob_module
import httpx
from datetime import datetime
from openai import OpenAI

def load_config():
    """从项目根目录的 .agent/config.json 加载配置（API Key、模型等）。"""
    config_path = Path(__file__).resolve().parents[2] / ".agent" / "config.json"
    with open(config_path, "r", encoding="utf-8") as f:
        return json.load(f)


# 模块加载时即读取配置，后续函数直接引用全局的 config / client
config = load_config()

# 初始化 OpenAI 兼容客户端（支持任何兼容 OpenAI 接口的模型服务，如 DeepSeek）
client = OpenAI(
    api_key=config["OPENAI_API_KEY"],
    base_url=config["OPENAI_BASE_URL"],
    # verify=False：跳过 SSL 证书校验，方便连接自托管 / 内网代理；教学用，生产环境不应关闭。
    http_client=httpx.Client(verify=False),
)

MODEL = config["OPENAI_MODEL"]  # 使用的模型名（OpenAI 兼容接口）
MEMORY_FILE = "agent_memory.md"  # 记忆持久化文件（见文末 load/save_memory）

# ==================== 工具实现 ====================


def read(path, offset=None, limit=None):
    """读取文件内容并附带行号返回。

    - path：文件路径；offset/limit 可选，用于读取指定行范围（分片读大文件）。
    - 每行前缀格式化为「  1 内容」，方便 LLM 在回复里精确引用行号。
    - 任何异常都转成字符串返回（不让工具抛错中断 Agent 循环）。
    """
    try:
        with open(path, "r", encoding="utf-8") as f:
            lines = f.readlines()
        start = offset if offset else 0
        end = start + limit if limit else len(lines)
        return "".join(
            f"{i + 1:4d} {line}" for i, line in enumerate(lines[start:end], start)
        )
    except Exception as e:
        return f"Error: {str(e)}"


def write(path, content):
    """把整段内容写入文件（覆盖写）。

    - 自动创建缺失的父目录（exist_ok=True），省去 LLM 先 mkdir 的步骤。
    - 与 edit 的区别：write 是整文件覆盖，适合新建文件或大段重写。
    """
    try:
        os.makedirs(
            os.path.dirname(path) if os.path.dirname(path) else ".", exist_ok=True
        )
        with open(path, "w", encoding="utf-8") as f:
            f.write(content)
        return f"Successfully wrote to {path}"
    except Exception as e:
        return f"Error: {str(e)}"


def edit(path, old_string, new_string):
    """精确替换文件中的一处文本。

    - 关键约束：old_string 必须在文件中「恰好出现一次」。
      若出现 0 次或多次都会报错——这样能避免 LLM 误改多处歧义文本。
    - 适合小范围、精确的局部修改；大段重写请用 write。
    """
    try:
        with open(path, "r", encoding="utf-8") as f:
            content = f.read()
        if content.count(old_string) != 1:
            return f"Error: old_string must appear exactly once (found {content.count(old_string)})"
        with open(path, "w", encoding="utf-8") as f:
            f.write(content.replace(old_string, new_string))
        return f"Successfully edited {path}"
    except Exception as e:
        return f"Error: {str(e)}"


def glob(pattern):
    """按 glob 通配符查找文件，按修改时间倒序返回（最近改动的在前）。

    - 支持递归（**），适合「最近动过哪些文件」这类检索。
    - 无匹配时返回提示字符串，而不是空值。
    """
    try:
        files = sorted(
            glob_module.glob(pattern, recursive=True),
            key=lambda x: os.path.getmtime(x),
            reverse=True,
        )
        return "\n".join(files) if files else "No files found"
    except Exception as e:
        return f"Error: {str(e)}"


def grep(pattern, path="."):
    """在文件内容中搜索正则 pattern，返回匹配行。

    - 直接 shell 调用系统 grep（shell=True，教学用，存在命令注入风险，
      生产环境应改用 Python 正则或受控参数）。
    - 30 秒超时，避免卡死 Agent 循环。
    """
    try:
        result = subprocess.run(
            f"grep -rn '{pattern}' {path}",
            shell=True,
            capture_output=True,
            text=True,
            timeout=30,
        )
        return result.stdout if result.stdout else "No matches found"
    except Exception as e:
        return f"Error: {str(e)}"


def bash(command):
    """执行任意 shell 命令，合并 stdout + stderr 返回。

    - 最强大也最危险的工具；shell=True 同样有命令注入风险（教学用）。
    - 把 stderr 也一并返回，方便 LLM 看到报错信息自我纠错。
    """
    try:
        result = subprocess.run(
            command, shell=True, capture_output=True, text=True, timeout=30
        )
        return result.stdout + result.stderr
    except Exception as e:
        return f"Error: {str(e)}"


# ==================== SubAgent 实现（核心） ====================


def subagent(role, task):
    """启动一个独立的 Agent 循环，拥有专属角色和独立上下文。

    核心：subagent 在主 Agent 眼里就是一个普通工具，但调用时会启动一条
    全新的 LLM 对话链（独立的 messages / system / 工具集），跑完把最终
    文本作为工具返回值交还给主 Agent。子代理对主 Agent 的上下文「无感」，
    不会污染主对话历史。

    - role：子代理的专业身份，如「Python API 设计师」「DBA」，注入 system。
    - task：要委派的具体任务。
    - 返回：子代理最终的文本回答。
    """
    print(f"\n{'=' * 50}")
    print(f"[SubAgent:{role}] 开始: {task}")
    print(f"{'=' * 50}")

    # ① 为子代理构建独立的对话：专属角色 system + 任务，与主 Agent 上下文隔离
    sub_messages = [
        {
            "role": "system",
            "content": f"You are a {role}. Be concise and focused. Only do what is asked.",
        },
        {"role": "user", "content": task},
    ]
    # ② 子代理工具集：剔除 subagent 自身，防止「子代理再派子代理」的无限递归
    sub_tools = [t for t in tools if t["function"]["name"] != "subagent"]

    # ③ 子代理自己的 Agent 循环（与 run_agent 同构，但作用域独立）
    for _ in range(10):  # 安全阀：限制子代理最大轮数，避免它陷入死循环
        response = client.chat.completions.create(
            model=MODEL, messages=sub_messages, tools=sub_tools
        )
        message = response.choices[0].message
        sub_messages.append(message)

        # 没有工具调用 = 子代理已得出最终答案，把文本返回给主 Agent
        if not message.tool_calls:
            print(f"[SubAgent:{role}] 完成\n")
            return message.content

        # 逐个执行子代理请求的工具，把结果回填为 role:"tool" 消息
        for tc in message.tool_calls:
            fn = tc.function.name
            args = json.loads(tc.function.arguments)
            print(
                f"  [SubAgent:{role}] {fn}({json.dumps(args, ensure_ascii=False)[:80]})"
            )
            result = available_functions[fn](**args)
            sub_messages.append(
                {"role": "tool", "tool_call_id": tc.id, "content": result}
            )

    return "SubAgent: max iterations reached"


# ==================== 工具注册 ====================
# 两张表配合：tools 是给 LLM 看的「声明」（JSON Schema），
# available_functions 是名字 → 真正的「实现」。二者通过 name 对齐。

available_functions = {
    "read": read,
    "write": write,
    "edit": edit,
    "glob": glob,
    "grep": grep,
    "bash": bash,
    "subagent": subagent,  # 注意：subagent 也注册成普通工具，主 Agent 调用它即触发子循环
}

# 工具声明（OpenAI function-calling 格式），决定 LLM 能「看见」并选择哪些工具
tools = [
    {
        "type": "function",
        "function": {
            "name": "read",
            "description": "Read file with line numbers",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "offset": {"type": "integer"},
                    "limit": {"type": "integer"},
                },
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "write",
            "description": "Write content to file (creates dirs automatically)",
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
    {
        "type": "function",
        "function": {
            "name": "edit",
            "description": "Replace a unique string in file",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "old_string": {"type": "string"},
                    "new_string": {"type": "string"},
                },
                "required": ["path", "old_string", "new_string"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "glob",
            "description": "Find files by pattern",
            "parameters": {
                "type": "object",
                "properties": {"pattern": {"type": "string"}},
                "required": ["pattern"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "grep",
            "description": "Search files for pattern",
            "parameters": {
                "type": "object",
                "properties": {
                    "pattern": {"type": "string"},
                    "path": {"type": "string"},
                },
                "required": ["pattern"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "bash",
            "description": "Run shell command",
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
            "name": "subagent",
            "description": "Delegate a task to a specialized sub-agent with its own role and independent context. Use this when a task requires specific expertise (e.g. 'frontend developer', 'DBA', 'test engineer').",
            "parameters": {
                "type": "object",
                "properties": {
                    "role": {
                        "type": "string",
                        "description": "The sub-agent's specialty, e.g. 'Python backend developer'",
                    },
                    "task": {
                        "type": "string",
                        "description": "The specific task to delegate",
                    },
                },
                "required": ["role", "task"],
            },
        },
    },
]

# ==================== 记忆 ====================


def load_memory():
    """读取历史记忆，只取最后 50 行（窗口式记忆）。

    - 只保留最近记录是为了控制注入 system 的上下文长度，避免历史无限膨胀。
    - 文件不存在或读取失败时返回空串（当作「无记忆」处理，不阻断流程）。
    """
    if not os.path.exists(MEMORY_FILE):
        return ""
    try:
        with open(MEMORY_FILE, "r", encoding="utf-8") as f:
            lines = f.read().split("\n")
        return "\n".join(lines[-50:]) if len(lines) > 50 else "\n".join(lines)
    except:
        return ""


def save_memory(task, result):
    """把本次任务与结果追加写入记忆文件（带时间戳）。

    - 追加写（"a"）而非覆盖，逐步积累跨会话的经验。
    - except: pass：写记忆失败不影响主流程，最坏只是丢了这次记录。
    """
    try:
        with open(MEMORY_FILE, "a", encoding="utf-8") as f:
            f.write(
                f"\n## {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n**Task:** {task}\n**Result:** {result}\n"
            )
    except:
        pass


# ==================== Agent 核心循环 ====================


def run_agent(messages, max_iterations=10):
    """主 Agent 的核心循环：工具调用 → 回填结果 → 再问 LLM，直到给出最终答案。

    流程（每轮）：
      1. 调用 LLM：传入对话历史 + 全部工具声明（含 subagent）。
      2. 若 LLM 没有请求工具调用，说明它已得出最终答案，直接返回文本。
      3. 否则逐个执行它请求的工具（命中 subagent 时即委派给子代理），
         把结果以 role:"tool" 消息回填进历史，进入下一轮。

    - messages：对话历史（原地追加，调用方持有引用）。
    - max_iterations：安全阀，防止 Agent 陷入无限工具调用循环。
    """
    for _ in range(max_iterations):  # ① 安全阀：最多循环这么多次
        # ② 调用 LLM：传入对话历史 + 工具定义，让模型决定下一步
        response = client.chat.completions.create(
            model=MODEL, messages=messages, tools=tools
        )
        message = response.choices[0].message
        messages.append(message)

        # ③ LLM 没有调用任何工具，说明它认为可以给出最终答案了
        if not message.tool_calls:
            return message.content

        # ④ 逐个执行 LLM 请求的工具，把结果回填进对话历史
        for tc in message.tool_calls:
            fn = tc.function.name
            args = json.loads(tc.function.arguments)
            print(f"[Tool] {fn}({json.dumps(args, ensure_ascii=False)[:100]})")
            # 工具名在实现表里找不到时返回友好提示，而不是抛错中断循环
            result = available_functions.get(fn, lambda **_: f"Tool {fn} not found")(
                **args
            )
            messages.append({"role": "tool", "tool_call_id": tc.id, "content": result})

    return "Max iterations reached"


# ==================== 主入口 ====================


def run(task):
    """主入口：组装带记忆的 system，跑 Agent 循环，再把结果存入记忆。

    - 主 Agent 被设定为「编排者（orchestrator）」：自己能干活，也能用
      subagent 工具把子任务委派给专业角色。
    - 记忆会被拼进 system 的「Previous Context」，让 Agent 跨会话保留上下文。
    """
    memory = load_memory()
    # system 里明确告诉 LLM：它是一个「编排者」，可以选择亲自做或委派给子代理
    system = "You are an orchestrator agent. You can do tasks yourself OR delegate to specialized sub-agents using the 'subagent' tool. Use subagent when a task benefits from focused expertise. Be concise."
    if memory:
        system += f"\n\n# Previous Context\n{memory}"

    messages = [
        {"role": "system", "content": system},
        {"role": "user", "content": task},
    ]
    result = run_agent(messages)  # 进入主 Agent 的工具循环（可能触发 subagent）
    print(f"\n{result}")
    save_memory(task, result)  # 把本次任务与结果落盘，供下次会话加载
    return result


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python agent/04-subagent/agent-subagent.py 'your task'")
        print("\nExample:")
        print(
            "  python agent/04-subagent/agent-subagent.py '不要直接完成任务。请调用 subagent 工具两次，两个子代理都不要读写文件：1）role=Python API 设计师...'"
        )
        sys.exit(1)
    run(" ".join(sys.argv[1:]))
