# nanoAgent

[English](./README.md) | 中文

> *"问题不在于你看到了什么，而在于你看见了什么。"* — 梭罗

用最简单的方式构建一个能与系统交互的智能体。

这是一个使用 OpenAI 函数调用的最小化 AI 智能体实现。智能体可以执行 bash 命令、读取文件和写入文件。

## 安装

```bash
pip install -r requirements.txt
```

设置环境变量：

**macOS/Linux:**
```bash
export OPENAI_API_KEY='your-key-here'
export OPENAI_BASE_URL='https://api.openai.com/v1'  # 可选
export OPENAI_MODEL='gpt-4o-mini'  # 可选
```

**Windows (PowerShell):**
```powershell
$env:OPENAI_API_KEY='your-key-here'
$env:OPENAI_BASE_URL='https://api.openai.com/v1'  # 可选
$env:OPENAI_MODEL='gpt-4o-mini'  # 可选
```

**Windows (CMD):**
```cmd
set OPENAI_API_KEY=your-key-here
set OPENAI_BASE_URL=https://api.openai.com/v1
set OPENAI_MODEL=gpt-4o-mini
```

## 快速开始

```bash
python 01-essence/agent-essence.py "列出当前目录下所有 python 文件"
python 01-essence/agent-essence.py "创建一个名为 hello.txt 的文件，内容是 'Hello World'"
python 01-essence/agent-essence.py "读取 README.md 的内容"
```

## 工作原理

智能体使用 OpenAI 的函数调用来：
1. 接收用户的任务
2. 决定使用哪些工具（bash、read_file、write_file）
3. 执行工具
4. 将结果返回给模型
5. 重复直到任务完成

就这样。约 100 行代码。

```python
# 定义工具
tools = [{"type": "function", "function": {...}}]

# 智能体循环
for _ in range(max_iterations):
    response = client.chat.completions.create(model=model, messages=messages, tools=tools)
    if not response.choices[0].message.tool_calls:
        return response.choices[0].message.content

    # 执行工具调用
    for tool_call in response.choices[0].message.tool_calls:
        result = available_functions[tool_call.function.name](**args)
        messages.append({"role": "tool", "content": result})
```

核心就是一个循环：调用模型 → 执行工具 → 重复。

## 能力

- `execute_bash`: 运行任何 bash 命令
- `read_file`: 读取文件内容
- `write_file`: 写入内容到文件

## 示例

```bash
# 系统操作
python 01-essence/agent-essence.py "当前目录是什么，里面有哪些文件？"

# 文件操作
python 01-essence/agent-essence.py "创建一个打印 hello world 的 python 脚本"

# 组合任务
python 01-essence/agent-essence.py "找到所有 .py 文件并统计总代码行数"
```

---

## 系列文章

**「从零开始理解 Agent」** —— 7 篇文章，7 个代码文件，逐层拆解。

| # | 目录 | 文章 | 代码 | 行数 |
|---|------|------|------|------|
| 01 | [01-essence/](./01-essence/) | [底层原理，只有 100 行](./01-essence/agent-essence.md) | `agent-essence.py` | 103 |
| 02 | [02-memory/](./02-memory/) | [记忆与规划](./02-memory/agent-memory.md) | `agent-memory.py` | 206 |
| 03 | [03-skills-mcp/](./03-skills-mcp/) | [Rules、Skills 与 MCP](./03-skills-mcp/agent-skills-mcp.md) | `agent-skills-mcp.py` | 282 |
| 04 | [04-subagent/](./04-subagent/) | [SubAgent 子智能体](./04-subagent/agent-subagent.md) | `agent-subagent.py` | 192 |
| 05 | [05-teams/](./05-teams/) | [多智能体团队协作](./05-teams/agent-teams.md) | `agent-teams.py` | 270 |
| 06 | [06-compact/](./06-compact/) | [上下文压缩](./06-compact/agent-compact.md) | `agent-compact.py` | 169 |
| 07 | [07-safety/](./07-safety/) | [三道安全防线](./07-safety/agent-safe.md) | `agent-safe.py` | 219 |

→ [系列导读与目录](./README.md)

---

## 许可证

MIT

────────────────────────────────────────

⏺ *如同一粒种子长成森林，一个文件化作无限可能。*
