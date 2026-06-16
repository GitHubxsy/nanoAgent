"""
第 03 章:Rules、Skills 与 MCP —— 给 Agent 装上「外部能力」

本章在第 01 章（工具循环）的基础上，给 Agent 增加三类可加载的外部能力：

  - Rules  (规则)：从 .agent/rules/*.md 读入，作为「行为规范」拼进 system prompt。
  - Skills (技能)：从 .agent/skills/*/SKILL.md 读入，作为「操作手册」拼进 system prompt。
  - MCP    (工具)：从 .agent/mcp.json 读入，作为「外部工具声明」追加到 tools 列表。

关键区别：
  Rules / Skills 是「灌进大脑的知识」（写入 system prompt，影响 LLM 的思考）；
  MCP 是「新增加的手」（扩展 tools 列表，给 LLM 更多可调用的工具）。

运行方式：
  python agent/03-skills-mcp/agent-skills-mcp.py '你的任务'
"""

# ===================== 标准库与第三方依赖 =====================
import os
import json
import subprocess
import sys
import glob as glob_module
import httpx
from pathlib import Path
from typing import Any
from openai import OpenAI


def load_config():
    """从项目根目录的 .agent/config.json 加载配置（API Key、模型等）。

    注意：本章（与 01、02 章）只读 config.json，不读环境变量。
    parents[2] 表示从本文件向上跳两级目录，落到项目根目录。
    """
    config_path = Path(__file__).resolve().parents[2] / ".agent" / "config.json"
    with open(config_path, "r", encoding="utf-8") as f:
        return json.load(f)


# 模块加载时即读取配置，后续函数直接引用全局的 config / client
config = load_config()

# 初始化 OpenAI 兼容客户端（支持任何兼容 OpenAI 接口的模型服务）
# verify=False：跳过 SSL 证书校验，方便连接自托管 / 内网代理；教学用，生产环境不应关闭。
client = OpenAI(
    api_key=config["OPENAI_API_KEY"],
    base_url=config["OPENAI_BASE_URL"],
    http_client=httpx.Client(verify=False),
)

# ===================== 外部能力相关路径与常量 =====================
# 这里用相对路径（依赖「当前工作目录」），换目录运行会失效，详见正文讲解的「坑 4」。
RULES_DIR = "../../.agent/rules"
SKILLS_DIR = "../../.agent/skills"
MCP_CONFIG = "../../.agent/mcp.json"
DEFAULT_MAX_ITERATIONS = 20  # Agent 循环最多执行的轮数（兜底，防止无限调用工具）


# ===================== 内置工具的「声明」（契约） =====================
# base_tools 是给 LLM 看的：每个条目描述一个工具的名字、用途、参数 schema。
# 它只负责「声明」，真正的实现在下面的同名 Python 函数里，二者靠名字配对。
base_tools = [
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
            "description": "Write content to file",
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
            "description": "Replace string in file",
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
]


# ===================== 内置工具的「实现」 =====================
# 下面每个函数与 base_tools / available_functions 里的名字一一对应。
# 所有实现都做了 try/except 兜底：出错时返回字符串形式的错误信息，
# 这样错误会被当作工具结果回传给 LLM，而不是直接抛崩让 Agent 停摆。


def read(path, offset=None, limit=None):
    """读取文件并加上行号；可用 offset/limit 读取指定区间。"""
    try:
        with open(path, "r", encoding="utf-8") as f:
            lines = f.readlines()
        start = offset if offset else 0
        end = start + limit if limit else len(lines)
        numbered = [
            f"{i + 1:4d} {line}" for i, line in enumerate(lines[start:end], start)
        ]
        return "".join(numbered)
    except Exception as e:
        return f"Error: {str(e)}"


def write(path, content):
    """将内容写入文件（覆盖写）。"""
    try:
        with open(path, "w", encoding="utf-8") as f:
            f.write(content)
        return f"Successfully wrote to {path}"
    except Exception as e:
        return f"Error: {str(e)}"


def edit(path, old_string, new_string):
    """在文件中精确替换一段字符串。

    要求 old_string 在文件里「恰好出现一次」，否则报错——
    这是为了避免歧义替换改错地方（调用方需提供足够独特的片段）。
    """
    try:
        with open(path, "r", encoding="utf-8") as f:
            content = f.read()
        if content.count(old_string) != 1:
            return f"Error: old_string must appear exactly once"
        new_content = content.replace(old_string, new_string)
        with open(path, "w", encoding="utf-8") as f:
            f.write(new_content)
        return f"Successfully edited {path}"
    except Exception as e:
        return f"Error: {str(e)}"


def glob(pattern):
    """按通配符查找文件，按修改时间倒序返回（最近改的排最前）。"""
    try:
        files = glob_module.glob(pattern, recursive=True)
        files.sort(key=lambda x: os.path.getmtime(x), reverse=True)
        return "\n".join(files) if files else "No files found"
    except Exception as e:
        return f"Error: {str(e)}"


def grep(pattern, path="."):
    """在指定路径下递归搜索文本。

    注意：这里用 f-string 拼接 shell 命令，存在命令注入风险，仅作教学演示。
    """
    try:
        result = subprocess.run(
            f"grep -r '{pattern}' {path}",
            shell=True,
            capture_output=True,
            text=True,
            timeout=30,
        )
        return result.stdout if result.stdout else "No matches found"
    except Exception as e:
        return f"Error: {str(e)}"


def bash(command):
    """执行任意 shell 命令，返回 stdout+stderr 拼接结果。

    注意：shell=True 直接执行任意命令，教学用；生产环境需做黑名单/白名单过滤。
    """
    try:
        result = subprocess.run(
            command, shell=True, capture_output=True, text=True, timeout=30
        )
        return result.stdout + result.stderr
    except Exception as e:
        return f"Error: {str(e)}"


def demo_release_policy(topic="发布演示"):
    """演示用的 MCP 工具实现：返回一段「发布策略」说明，只读不改文件。"""
    return (
        f"{topic} 的 MCP 发布策略：本次只做演示，不修改文件；"
        "发布前先保数据安全，再保应用能启动，最后处理界面文案。"
    )


# 「名字 → 实现」的映射表：Agent 循环里按 LLM 给出的函数名在这里查实现并执行。
# 注意：MCP 声明的工具并未加入此表，因此本 demo 中 MCP 工具被调用时会走到「Unknown tool」分支。
available_functions = {
    "read": read,
    "write": write,
    "edit": edit,
    "glob": glob,
    "grep": grep,
    "bash": bash,
    "demo_release_policy": demo_release_policy,
}


def parse_tool_arguments(raw_arguments: str) -> dict[str, Any]:
    """把 LLM 返回的工具参数（字符串形态）解析成 dict。

    有些兼容端点会把 arguments 以字符串形式返回，需先 json.loads。
    解析失败时不抛异常，而是返回一个带 _argument_error 的标记字典，
    让上层把它当作错误结果回传给 LLM（LLM 可据此修正重试）。
    """
    if not raw_arguments:
        return {}
    try:
        parsed = json.loads(raw_arguments)
        return parsed if isinstance(parsed, dict) else {}
    except json.JSONDecodeError as error:
        return {"_argument_error": f"Invalid JSON arguments: {error}"}


# ===================== Rules：行为规范 =====================


def load_rules():
    """读取 .agent/rules/ 下所有 .md 规则文件，拼成一大段文本。

    每个 markdown 文件名（去扩展名）作为小标题。读不到目录或出错时返回空串，
    保证没有规则文件时 Agent 仍能正常运行。
    """
    rules = []
    if not os.path.exists(RULES_DIR):
        return ""
    try:
        for rule_file in sorted(Path(RULES_DIR).glob("*.md")):
            with open(rule_file, "r", encoding="utf-8") as f:
                rules.append(f"# {rule_file.stem}\n{f.read()}")
        return "\n\n".join(rules) if rules else ""
    except:
        return ""


def count_rule_files():
    """统计规则文件数量，仅用于启动时打印日志。"""
    if not os.path.exists(RULES_DIR):
        return 0
    return len(list(Path(RULES_DIR).glob("*.md")))


# ===================== Skills：操作手册 =====================


def load_skills():
    """读取 .agent/skills/ 下的技能文件。

    支持两种布局：
      - skills/<name>/SKILL.md   （目录式，优先）
      - skills/<name>.md         （扁平式，兜底）
    每个文件经 parse_markdown_skill 解析成结构化字典。
    """
    skills = []
    if not os.path.exists(SKILLS_DIR):
        return []
    try:
        skill_files = sorted(Path(SKILLS_DIR).glob("*/SKILL.md")) + sorted(
            Path(SKILLS_DIR).glob("*.md")
        )
        for skill_file in skill_files:
            skills.append(parse_markdown_skill(skill_file))
        return skills
    except:
        return []


def parse_markdown_skill(path):
    """解析单个 Skill markdown 文件，提取 frontmatter 元数据 + 正文。

    frontmatter 是文件开头的 --- ... --- 块，形如：
        ---
        name: my-skill
        description: ...
        when_to_use: ...
        triggers: a, b, c
        ---
    元数据缺失时给合理默认值：name 取目录名或文件名，triggers 拆成小写列表。
    """
    content = path.read_text(encoding="utf-8")
    metadata = {}
    body = content
    if content.startswith("---\n"):
        end = content.find("\n---", 4)
        if end != -1:
            frontmatter = content[4:end].strip()
            body = content[end + 4 :].strip()
            for line in frontmatter.splitlines():
                if ":" not in line:
                    continue
                key, value = line.split(":", 1)
                metadata[key.strip()] = value.strip()
    # 推断技能名：优先用 frontmatter 的 name；否则目录式取目录名、扁平式取文件名
    name = metadata.get(
        "name", path.parent.name if path.name == "SKILL.md" else path.stem
    )
    # triggers 以逗号分隔，统一转小写方便后续匹配
    triggers = [
        trigger.strip().lower()
        for trigger in metadata.get("triggers", "").split(",")
        if trigger.strip()
    ]
    return {
        "name": name,
        "description": metadata.get("description", ""),
        "when_to_use": metadata.get("when_to_use", ""),
        "triggers": triggers,
        "path": str(path),
        "content": body,
    }


def format_skill_for_prompt(skill):
    """把一个技能字典格式化为要拼进 system prompt 的文本块。"""
    lines = [
        f"## {skill['name']}",
        f"Source: {skill['path']}",
        f"Description: {skill.get('description', '')}",
    ]
    when_to_use = skill.get("when_to_use")
    if when_to_use:
        lines.append(f"When to use: {when_to_use}")
    if skill.get("triggers"):
        lines.append(f"Triggers: {', '.join(skill['triggers'])}")
    lines.append(skill["content"])
    return "\n".join(lines)


# ===================== MCP：外部工具声明 =====================


def load_mcp_tools():
    """从 .agent/mcp.json 读取 MCP 工具声明，转成与 base_tools 相同的结构。

    只读取未被 disabled 的服务器下的 tools，把它们追加进工具列表，
    让 LLM 「看得见、能调用」。注意：本 demo 不提供这些工具的 Python 实现，
    因此 LLM 真正调用时会命中 run_agent_step 里的「Unknown tool」分支。
    """
    if not os.path.exists(MCP_CONFIG):
        return []
    try:
        with open(MCP_CONFIG, "r", encoding="utf-8") as f:
            config = json.load(f)
            mcp_tools = []
            for server_name, server_config in config.get("mcpServers", {}).items():
                if server_config.get("disabled", False):
                    continue
                for tool in server_config.get("tools", []):
                    mcp_tools.append({"type": "function", "function": tool})
            return mcp_tools
    except:
        return []


# ===================== 核心：Agent 循环 =====================


def run_agent_step(messages, tools, max_iterations=DEFAULT_MAX_ITERATIONS):
    """标准的「LLM ↔ 工具」ReAct 循环。

    每一轮：
      1. 把当前 messages 连同 tools 发给 LLM；
      2. 若 LLM 不再请求工具调用 → 认为任务完成，返回最终文本；
      3. 若 LLM 请求工具调用 → 逐个执行，把结果以 role=tool 追加回 messages，进入下一轮；
      4. 若跑满 max_iterations 仍未完成 → 返回兜底提示，避免无限循环。
    """
    for _ in range(max_iterations):
        response = client.chat.completions.create(
            model=config["OPENAI_MODEL"],
            messages=messages,
            tools=tools,
        )
        message = response.choices[0].message
        messages.append(message)
        # LLM 没有调用任何工具，说明它认为可以给出最终答案了
        if not message.tool_calls:
            return message.content, messages
        # 逐个执行 LLM 请求的工具调用
        for tool_call in message.tool_calls:
            function_payload = getattr(tool_call, "function", None)
            if function_payload is None:
                continue
            function_name = str(getattr(function_payload, "name", ""))
            raw_arguments = str(getattr(function_payload, "arguments", ""))
            function_args = parse_tool_arguments(raw_arguments)
            print(f"[Tool] {function_name}({function_args})")
            # 按名字查实现表
            function_impl = available_functions.get(function_name)
            if "_argument_error" in function_args:
                # 参数解析失败：把错误回传给 LLM，让它有机会修正
                function_response = f"Error: {function_args['_argument_error']}"
            elif function_impl is not None:
                # 正常执行工具，传入解析好的参数
                function_response = function_impl(**function_args)
            else:
                # 工具名在实现表里找不到（例如 MCP 声明了但没实现）
                function_response = f"Error: Unknown tool '{function_name}'"
            # 把工具执行结果以 tool 消息形式回传，tool_call_id 用于关联是哪次调用
            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": tool_call.id,
                    "content": function_response,
                }
            )
    return "Max iterations reached", messages


def run_agent_with_external_capabilities(task):
    """总装车间：加载三件外部能力 → 组装 system prompt → 启动 Agent 循环。"""
    rule_count = count_rule_files()
    rules = load_rules()
    skills = load_skills()
    mcp_tools = load_mcp_tools()
    # 工具列表 = 内置工具 + MCP 工具（Rules/Skills 不进工具列表，而是进 prompt）
    all_tools = base_tools + mcp_tools
    # system prompt 由「身份说明 + 规则 + 技能」拼接而成
    context_parts = [
        "You are a helpful assistant that can interact with the system. Be concise."
    ]
    if rules:
        context_parts.append(f"\n# Rules\n{rules}")
        print(f"[Rules] Loaded {rule_count} rule files")
    if skills:
        context_parts.append(
            f"\n# Skills\n"
            + "\n\n".join(format_skill_for_prompt(skill) for skill in skills)
        )
        skill_names = [skill["name"] for skill in skills]
        print(f"[Skills] Loaded {len(skills)} skill files: {', '.join(skill_names)}")
    if mcp_tools:
        tool_names = [tool["function"]["name"] for tool in mcp_tools]
        print(f"[MCP] Loaded {len(mcp_tools)} MCP tools: {', '.join(tool_names)}")
    # 组装消息：先是 system（身份+规则+技能），再是 user（任务）
    messages = [{"role": "system", "content": "\n".join(context_parts)}]
    messages.append({"role": "user", "content": task})
    # 进入 Agent 循环
    final_result, messages = run_agent_step(messages, all_tools)
    print(f"\n{final_result}")
    return final_result


if __name__ == "__main__":
    # 命令行入口：python agent/03-skills-mcp/agent-skills-mcp.py '你的任务'
    if len(sys.argv) < 2:
        print("Usage: python3 agent/03-skills-mcp/agent-skills-mcp.py 'your task'")
        print("\nFeatures: Rules, Skills, MCP")
        sys.exit(1)
    # 多个参数用空格拼成一个完整任务字符串
    task = " ".join(sys.argv[1:])
    run_agent_with_external_capabilities(task)
