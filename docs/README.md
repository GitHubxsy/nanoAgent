# 从零开始理解 Agent —— 系列导读

> 通过一个不到 300 行的开源项目 [nanoAgent](https://github.com/sanbuphy/nanoAgent)，逐层拆解 OpenClaw / Claude Code 等 AI Agent 背后的全部核心概念。

---

## 这个系列讲什么

很多人会用 ChatGPT，但不理解 Agent。这个系列从一个仅 **103 行**的极简实现出发，每篇增加一个核心能力，最终搭建出涵盖记忆、规划、工具扩展、多智能体、安全等所有关键特性的完整 Agent。

**一句话总结：** Agent = LLM + 工具 + 循环。理解了这个，你就理解了 Claude Code、Cursor、Devin 的底层。

---

## 七篇文章 × 七个代码文件

| # | 主题 | 文章 | 配套代码 | 代码行数 | 核心新增 |
|---|------|------|----------|----------|----------|
| 01 | 底层原理 | [第一篇：工具 + 循环](./nanoAgent-01-essence.md) | [`agent.py`](../agent.py) | 103 行 | Agent 最小实现 |
| 02 | 记忆与规划 | [第二篇：记忆 + 规划](./nanoAgent-02-memory.md) | [`agent-plus.py`](../agent-plus.py) | 206 行 | 持久记忆、任务分解 |
| 03 | Rules / Skills / MCP | [第三篇：行为规范与工具扩展](./nanoAgent-03-rules-skills-mcp.md) | [`agent-claudecode.py`](../agent-claudecode.py) | 282 行 | 规则约束、技能复用、MCP 协议 |
| 04 | SubAgent | [第四篇：一次性子智能体](./nanoAgent-04-subagent.md) | [`agent-subagent.py`](../agent-subagent.py) | 192 行 | 并行子任务 |
| 05 | 多智能体团队 | [第五篇：持久多智能体协作](./nanoAgent-05-teams.md) | [`agent-teams.py`](../agent-teams.py) | 270 行 | 团队身份、持久通信 |
| 06 | 上下文压缩 | [第六篇：不会撑爆 Context 的 Agent](./nanoAgent-06-compact.md) | [`agent-compact.py`](../agent-compact.py) | 169 行 | 自动摘要压缩 |
| 07 | 安全防线 | [第七篇：让 Agent 不做坏事](./nanoAgent-07-safety.md) | [`agent-safe.py`](../agent-safe.py) | 219 行 | 黑名单、人工确认、输出截断 |
| — | 七篇合一 | — | [`agent-full.py`](../agent-full.py) | 507 行 | 完整集成版 |

---

## 推荐阅读路径

### 路径 A：从头到尾（推荐新手）

```
第一篇 → 第二篇 → 第三篇 → 第四篇 → 第五篇 → 第六篇 → 第七篇
  │         │         │         │         │         │         │
agent.py  plus.py  cc.py    sub.py  teams.py compact.py safe.py
```

每篇都建立在前一篇基础上，逐层添加新特性。

### 路径 B：按需跳入（推荐有基础的读者）

- 只想理解 **Agent 原理** → 直接读[第一篇](./nanoAgent-01-essence.md)
- 想让 Agent **记住历史** → 直接读[第二篇](./nanoAgent-02-memory.md)
- 想接入 **MCP / 自定义工具** → 直接读[第三篇](./nanoAgent-03-rules-skills-mcp.md)
- 想做 **并行任务分解** → 直接读[第四篇](./nanoAgent-04-subagent.md)
- 想做 **多 Agent 协作** → 直接读[第五篇](./nanoAgent-05-teams.md)
- 担心 **Context 爆满** → 直接读[第六篇](./nanoAgent-06-compact.md)
- 担心 **Agent 搞破坏** → 直接读[第七篇](./nanoAgent-07-safety.md)
- 想要**一个文件搞定所有** → 直接看 [`agent-full.py`](../agent-full.py)

### 路径 C：只看代码

所有代码都在项目根目录，每个文件顶部的 docstring 就是对应篇章的摘要。

---

## 各篇章核心概念速查

| 概念 | 出现篇章 | 关键代码位置 |
|------|----------|--------------|
| Tool Schema / Function Calling | 第一篇 | `agent.py:16-60` |
| Agent Loop（核心循环） | 第一篇 | `agent.py:62-100` |
| 持久记忆（Persistent Memory） | 第二篇 | `agent-plus.py:99-117` |
| 任务规划（Planning） | 第二篇 | `agent-plus.py:119-142` |
| Rules（行为规则） | 第三篇 | `agent-claudecode.py:143-153` |
| Skills（可复用技能） | 第三篇 | `agent-claudecode.py:155-165` |
| MCP 工具加载 | 第三篇 | `agent-claudecode.py:167-181` |
| SubAgent（子智能体） | 第四篇 | `agent-subagent.py` |
| 多智能体通信 | 第五篇 | `agent-teams.py` |
| Context 压缩 | 第六篇 | `agent-compact.py` |
| 安全黑名单 | 第七篇 | `agent-safe.py` |

---

## 快速上手

```bash
git clone https://github.com/sanbuphy/nanoAgent.git
cd nanoAgent
pip install -r requirements.txt

export OPENAI_API_KEY="your-key"
export OPENAI_BASE_URL="https://api.openai.com/v1"  # 或 DeepSeek/Qwen 等

# 从第一篇开始
python agent.py "列出当前目录下所有 Python 文件"

# 带记忆的版本
python agent-plus.py "统计代码行数并记住结果"

# 完整版（集成所有特性）
python agent-full.py "重构 hello.py，添加类型注解和单元测试"
```

---

*本系列基于 [sanbuphy/nanoAgent](https://github.com/sanbuphy/nanoAgent)，MIT 许可。*
