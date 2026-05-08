# 从零开始做 Multi-Agent 系统 —— 系列导读

> 第四部。前三部讲"理解"，这一部讲"做"。

## 这个系列讲什么

多 Agent（Multi-Agent）是一个**听起来高级、但边界模糊**的话题。市面上 80% 的多 Agent 教程在抄框架 API，没讲清楚它的真实代价：通信开销、状态一致性、错误放大、调试地狱。

这个系列走另一条路——**围绕同一个 demo 项目**，从单 Agent baseline 开始，每章往多 Agent 方向多走一步，每一步都让 demo 真的多跑通一点；最后回头算账，看哪些步是真的赚了、哪些是"沟通税"。

立场：**在合适场景能跑通**，不万能、也不否定。

读完这个系列，你会理解：

- 什么场景单 Agent + 工具就够了，什么场景真的需要多 Agent
- 多 Agent 之间用消息、共享内存还是文件系统通信
- Supervisor / Workflow / Swarm 三种编排各自的代价
- 多 Agent 系统的真实失败模式与可观测性挑战
- 什么时候该退回单 Agent——以及为什么 Anthropic 自己说《Don't Build Multi-Agents》

---

## 贯穿 demo：自动化技术调研助手

输入一个技术问题（比如"GPU 推理优化的最新方案对比"），多 Agent 协作产出一份研究报告。

选这个 demo 的理由：

- 不和 Coding Agent 系列冲突
- 多 Agent 价值明显：搜索、总结、批判、整合分得开
- 失败模式天然丰富（信息冲突、过度搜索、关键漏检）
- 有 Anthropic《Multi-Agent Research System》博客作参照，但我们走"从零开始造"的路子，不依赖框架

---

## 文章目录

| # | 标题 | 这一章 demo 长出什么 |
|---|------|---------------------|
| 01 | [什么时候单 Agent 不够](./01-when-single-agent-fails/) | 单 Agent baseline，亲眼看到它在哪些地方崩 |
| 02 | [最小多 Agent 骨架：Supervisor + Workers](./02-minimum-skeleton/) | Planner + 并行 Searcher + Writer，第一版可跑 |
| 03 | [Agent 之间怎么传话：消息、共享状态、文件](./03-communication/) | 数据通路成型：Searcher 写文件，Writer 读文件 |
| 04 | [编排模式之争：Supervisor / Workflow / Swarm](./04-orchestration/) | 三种模式各重写一遍，对比后选定混合方案 |
| 05 | [状态、记忆与上下文：每个 Agent 自带 vs 共享](./05-state-memory/) | shared scratchpad 解决去重和信息冲突 |
| 06 | [错误传播、重试与可观测性](./06-failure-trace/) | 加 critic + 重试 + trace，demo 能真正交付 |
| 07 | [边界与反模式：什么时候该退回单 Agent](./07-boundaries/) | 算账：哪些 token 真的换来了价值 |

---

## 各章详细大纲

### 01 什么时候单 Agent 不够

**核心问题**：什么场景下单 Agent + 工具就够了？什么时候真需要多 Agent？

**主要小节**：
- 1.1 先做一个单 Agent baseline：能搜索 + 能写报告
- 1.2 让它做一次"GPU 推理优化方案调研"，看输出长什么样
- 1.3 单 Agent 在哪些地方崩了
  - Context 爆炸：搜索结果一多就装不下
  - 串行慢：5 个方向只能一个个查
  - 视角单一：没有 critic，错的也照单全收
  - 任务边界乱：搜索、总结、对比混在一个 prompt 里
- 1.4 这些是工具问题、prompt 问题，还是架构问题
- 1.5 多 Agent 能解什么、解不了什么（先打预防针）

**反常识点**：很多场景看起来需要多 Agent，其实是 prompt 没写好；只有当 **任务并行 + 视角多样 + 上下文隔离** 三件事同时需要时，多 Agent 才真的赢。

---

### 02 最小多 Agent 骨架：Supervisor + Workers

**核心问题**：从单 Agent 拆出多 Agent，第一刀怎么切？

**主要小节**：
- 2.1 拆分原则：按"职责"还是按"上下文边界"
- 2.2 第一版骨架：1 个 Planner（拆解问题）+ N 个 Searcher（并行搜）+ 1 个 Writer（整合输出）
- 2.3 Planner 怎么决定该拆几个 worker
- 2.4 Worker 之间需要互通吗？第一版假设不需要
- 2.5 跑一次 demo，对比第 01 章的单 Agent baseline
- 2.6 第一版的明显问题（埋后续章节的坑）

**反常识点**：第一刀一定要按"上下文边界"切，不是按"职责性感"切；Planner / Searcher / Writer 各占独立 context 才是核心收益。

---

### 03 Agent 之间怎么传话：消息、共享状态、文件

**核心问题**：多 Agent 之间到底用什么传数据？

**主要小节**：
- 3.1 三种主流通信方式
  - 消息：A → B 直接调用，参数传值
  - 共享内存：黑板模式，所有 Agent 读写同一份
  - 文件：Agent 把产物写进文件系统，下游读
- 3.2 三种方式的 token 成本、状态一致性、调试难度对比
- 3.3 给 demo 选定方案：Searcher 写文件、Writer 读文件、Planner 用消息发任务
- 3.4 为什么不全用消息：搜索结果太大，全塞进消息让 Planner 上下文爆炸
- 3.5 通信的失败模式：消息丢失、文件冲突、读写时序

**反常识点**：消息传递最简单，但最容易让上下文爆炸；很多多 Agent 系统其实是被"消息塞太满"拖垮的。

---

### 04 编排模式之争：Supervisor / Workflow / Swarm

**核心问题**：编排模式怎么选？三种各自的代价是什么？

**主要小节**：
- 4.1 三种模式的本质差异
  - Supervisor（主导型）：一个 Agent 调度其他 Agent
  - Workflow（流水线）：固定 DAG，每个节点是 Agent
  - Swarm（去中心化）：Agent 之间自主路由
- 4.2 用三种模式各重写一遍 demo
- 4.3 跑完对比：完成度、token、可控性、调试体验
- 4.4 调研场景的最佳选择：Supervisor 主导 + Workflow 收尾
- 4.5 什么场景该用 Swarm（剧透：很少）

**反常识点**：Swarm 看起来最"AI"，但生产环境里几乎没人用它；Workflow 不性感但最稳。

---

### 05 状态、记忆与上下文：每个 Agent 自带 vs 共享

**核心问题**：每个 Agent 应该有自己的记忆吗？还是共享一份？

**主要小节**：
- 5.1 三层状态：短期 context、长期 memory、跨 Agent 共享 state
- 5.2 Searcher 之间的去重问题：3 个 worker 都搜了同样的论文怎么办
- 5.3 信息冲突：Searcher A 说"FlashAttention 最快"，B 说"PagedAttention 最快"，谁对
- 5.4 给 demo 加一份 shared scratchpad：所有 Agent 可读，Planner 可写
- 5.5 共享状态的代价：竞态、过度共享会让 Agent 失去独立判断

**反常识点**：完全独立的 Agent 比看起来更慢更贵；过度共享的 Agent 又会"集体跑偏"——共享什么必须想清楚。

---

### 06 错误传播、重试与可观测性

**核心问题**：一个 Agent 跑挂了或者跑偏了，整个系统怎么办？

**主要小节**：
- 6.1 多 Agent 的失败模式：超时、幻觉、死锁（A 等 B、B 等 A）
- 6.2 加 critic Agent：输出前先批判一遍
- 6.3 重试策略：worker 失败重试 vs Planner 重新拆任务
- 6.4 trace 可视化：一次调研跑了多少 Agent、花了多少 token
- 6.5 用 trace 反推：哪个 worker 总浪费 token、哪个 critic 在装睡

**反常识点**：多 Agent 系统的"成功率"不是各 Agent 成功率相乘那么简单——错误会累积放大；不可观测的多 Agent 系统约等于不可用。

---

### 07 边界与反模式：什么时候该退回单 Agent

**核心问题**：做完 demo 回头看，哪些章节其实是被"多 Agent"过度设计了？

**主要小节**：
- 7.1 算账：demo 的 token 成本 vs 单 Agent baseline，多花了多少
- 7.2 拆解：哪些 token 是真的换来了价值，哪些是"沟通税"
- 7.3 反模式清单
  - 任务本身串行，硬拆多 Agent
  - Worker 之间需要频繁同步，沟通成本超过并行收益
  - 上下文小到单 Agent 装得下，没必要拆
  - 团队/产品压力让多 Agent 当 KPI 用
- 7.4 折中方案：单 Agent + SubAgent 临时调用，往往比多 Agent 团队更划算
- 7.5 什么时候多 Agent 真的值得：长任务（小时级以上）、并行收益高、上下文隔离刚需

**反常识点**：Anthropic 自己说《Don't Build Multi-Agents》，但 Claude Code 又用 SubAgent——区别在于"团队"和"临时帮手"的边界。

---

## 推荐阅读路径

### 路径 A：从头到尾（推荐）

```
01 → 02 → 03 → 04 → 05 → 06 → 07
```

每篇基于前一篇，demo 一步步长大；第 07 章回头算账，呼应第 01 章。

### 路径 B：按需跳入

- 想判断**自己的场景该不该上多 Agent** → 01 + 07
- 已经决定上，想知道**怎么拆** → 02 + 04
- 已经在跑，想解决**通信和状态问题** → 03 + 05
- 已经有系统，想解决**调试和可靠性** → 06

---

## 和其他系列的关系

这个系列是 [从零开始理解 Agent](../agent/README.md) 第 04 / 05 / 15 章的**实战延伸**：

- Agent 系列那 3 章是**概念入门**：SubAgent 是什么、编排有哪些模式、谁创建 Agent
- 这个系列是**做一遍给你看**：同样的概念，落地一次就知道哪里有坑

建议先读完 Agent 系列前 5 章再读本系列。Skill 系列不是前置，但读过 Skill 第 5 章（组合）会更容易理解第 04 章的编排模式。

---

## 状态

> 草稿大纲。代码与正文待写。
