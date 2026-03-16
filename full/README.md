# 七篇合一：完整 Agent

> **「从零开始理解 Agent」系列** 终章——将前七篇的所有核心功能集成到单个文件。

---

## 这是什么

[`agent-full.py`](./agent-full.py)（507 行）是整个系列的完整集成版，涵盖全部七篇的核心能力：

| 篇 | 能力 | 对应文件 |
|----|------|----------|
| 第一篇 | 工具 + 循环（read/write/edit/glob/grep/bash） | [01-essence/](../01-essence/) |
| 第二篇 | 记忆（agent_memory.md 持久化） | [02-memory/](../02-memory/) |
| 第三篇 | Rules + Skills + MCP | [03-skills-mcp/](../03-skills-mcp/) |
| 第四篇 | SubAgent（一次性子智能体） | [04-subagent/](../04-subagent/) |
| 第五篇 | Teams（持久多智能体协作） | [05-teams/](../05-teams/) |
| 第六篇 | 上下文压缩（compact_messages） | [06-compact/](../06-compact/) |
| 第七篇 | 安全防线（黑名单 + 用户确认 + 输出截断） | [07-safety/](../07-safety/) |

---

## 用法

```bash
# 标准模式
python full/agent-full.py "你的任务"

# 跳过用户确认（信任场景）
python full/agent-full.py --auto "你的任务"

# 使用多智能体团队模式
python full/agent-full.py --team "创建一个 TODO 应用，包含 Python 后端和 HTML 前端"
```

---

## 什么时候用这个文件？

- **学习完整系列后**想要一个开箱即用的完整版本
- **生产环境**需要综合所有能力的 Agent
- **对比参考**：将这 507 行与七个独立文件对照，理解各能力如何组合

如果你是初学者，建议从 [01-essence/](../01-essence/) 开始，逐篇阅读，最后再回到这里。

---

*← [返回系列导读](../README.md)*
