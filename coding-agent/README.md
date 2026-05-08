# 从零开始做 Coding Agent —— 系列导读

> 第四部备选。前三部讲"理解"，这一部讲"做"。

## 这个系列讲什么

Coding Agent（Claude Code、Cursor、Aider、Devin）是 2026 年最热的 Agent 落地场景。但市面上的内容大多停留在"怎么用"，很少讲清楚"为什么这样设计"——为什么 Edit 工具长这样、为什么 grep 默认赢过 embedding、为什么 git 操作要单独搞一套权限。

这个系列的路子：**围绕同一个 demo 项目**，从"会修单文件 bug 的最小 Agent"开始，每章往工程化方向多走一步，最终落到一个能接 GitHub PR 的 Coding Agent。

立场：**Coding Agent 的核心不是"会写代码"，而是"动作可逆 + 验证闭环"**——只要这两件事做对了，模型能力会被放大；做不对，再强的模型也会闯祸。

读完这个系列，你会理解：

- Coding Agent 和通用 Agent 的本质差别在哪
- Edit 工具语义之争（full-rewrite / search-replace / diff-apply / exact-string）为什么是 exact-string 赢
- 代码场景的上下文工程为什么 grep + Read 默认赢过 embedding
- 测试循环和 UI 验证为什么是两条独立的反馈回路
- git 为什么是 Coding Agent 唯一需要单独搞权限的工具
- SubAgent / Skill / Hook 在代码场景下分别长什么样
- 把 demo 接进 GitHub 后，哪些事仍然不该让它干

---

## 贯穿 demo：从 GitHub issue 到 PR 的 Coding Agent

输入一个 GitHub issue（"修复登录页 race condition"），输出一个能合并的 PR（含代码、测试、commit message）。

选这个 demo 的理由：

- 覆盖完整链路：读 issue → 仓库定位 → 改代码 → 跑测试 → UI 验证 → git → PR → review 响应
- 每一章都有具体可演示的能力
- 失败模式真实丰富（找错文件、测试没跑、改坏其他功能、commit 太大）
- 最终能接到自己的仓库里跑，看得见摸得着

---

## 文章目录

| # | 标题 | 这一章 demo 长出什么 |
|---|------|---------------------|
| 01 | [Coding Agent 特殊在哪](./01-what-is-coding-agent/) | 范围对齐 + demo 框架就位 |
| 02 | [最小骨架：Read / Edit / Bash 跑通一次修改](./02-minimum-skeleton/) | MVP，能修单文件 bug |
| 03 | [代码上下文工程：读什么、读多少、按什么顺序](./03-code-context/) | 能自己定位 bug 所在文件 |
| 04 | [红绿循环与自我验证：测试、错误、UI 验证](./04-feedback-loop/) | 改完会跑测试 + 启 dev server 截图 |
| 05 | [让 Agent 学会用 git](./05-git/) | 能产出可 review 的 commit |
| 06 | [工程化三件套：SubAgent、Skill、Hook](./06-engineering/) | 接近可托管的 Coding Agent |
| 07 | [Eval 与可观测性：做对了吗？跑偏了吗？](./07-eval-trace/) | 有"质量手柄"，回归不再黑箱 |
| 08 | [接进 GitHub 与人机边界](./08-github-boundaries/) | 真的能在自己的仓库里跑 |

---

## 各章详细大纲

### 01 Coding Agent 特殊在哪

**核心问题**：通用 Agent 已经能调工具了，为什么 Coding Agent 还要单独成一类？

**主要小节**：
- 1.1 通用 Agent baseline：用 Agent 系列第 03 章的实现跑一次"修 hello.py 的 bug"，看哪些地方不对
- 1.2 Coding 场景的四个特殊性：仓库感知、动作可逆性、测试闭环、长任务一致性
- 1.3 为什么 Read / Edit / Bash 这套"老三样"赢了，而不是更花哨的 IDE-like 抽象
- 1.4 选定 demo：从一个 GitHub issue 出发，最终提一个能合并的 PR

**反常识点**：Coding Agent 的核心不是"会写代码"，而是"动作可逆 + 验证闭环"——这两个对了，弱模型也能用；不对，再强的模型也会闯祸。

---

### 02 最小骨架：Read / Edit / Bash 跑通一次修改

**核心问题**：跑通一次完整的"理解 → 改 → 验证"需要哪几个工具？每个工具的语义为什么要那样设计？

**主要小节**：
- 2.1 三件套：Read（读文件）、Edit（精确替换）、Bash（跑命令）
- 2.2 Edit 工具的语义之争
  - Full rewrite：简单但每次都重写，token 烧
  - Search-replace：精确但容易碰多个匹配
  - Diff-apply：精确但 LLM 写 diff 容易错
  - Edit (exact string)：必须读过文件才能改，是最稳的工程妥协
- 2.3 Read 的语义：为什么要带行号、要分页、要拒绝过大文件
- 2.4 Bash 的语义：为什么要白名单 + 超时 + 工作目录持久化
- 2.5 跑一次最小 demo：让 Agent 修一个一行 bug

**反常识点**：Edit 工具的"必须先 Read 才能 Edit"看起来啰嗦，但它把 LLM 锁在"看过的事实"里——这是可逆性的根基。

---

### 03 代码上下文工程：读什么、读多少、按什么顺序

**核心问题**：仓库有几千个文件，Agent 怎么找到该改的那几行？

**主要小节**：
- 3.1 Coding 场景的上下文有三层：定位、相关、约束
- 3.2 三种定位策略对比
  - 全文搜索（grep）
  - 符号检索（LSP）
  - 语义检索（embedding）
- 3.3 为什么 Claude Code 默认用 grep + Read，而不是预先建 embedding
- 3.4 上下文优先级：README → CLAUDE.md → 相关代码 → 边缘文件
- 3.5 读多少才够：4K? 40K? 怎么知道读够了
- 3.6 demo 加上下文搜集：让 Agent 自己定位 bug 所在文件

**反常识点**：embedding 在代码场景常常输给 grep——代码命名是离散精确的，embedding 把"近义词"拉进来反而是噪声。

---

### 04 红绿循环与自我验证：测试、错误、UI 验证

**核心问题**：Agent 怎么知道自己改对了？光让模型自己说"我改完了"显然不够。

**主要小节**：
- 4.1 两条平行的反馈回路
  - 红绿循环：跑测试 → 看报错 → 修 → 再跑
  - UI / 集成验证：启 dev server → Playwright 点一下 → 截图比对
- 4.2 为什么 type-check 通过 ≠ 功能正确，单测通过 ≠ 端到端正确
- 4.3 错误归因：编译错？运行错？逻辑错？三种该怎么处理
- 4.4 何时该停手问人：循环 N 次都修不好的"硬错误"
- 4.5 demo 加上跑 pytest + 启 dev server 截图

**反常识点**：UI 验证不是测试的补充，而是另一条独立回路——它们会发现完全不同的问题，少一条都不够。

---

### 05 让 Agent 学会用 git

**核心问题**：git 是 Coding Agent 唯一一个"动作不可逆"的工具，怎么让它安全？

**主要小节**：
- 5.1 git 操作的可逆性光谱
  - 安全：status / diff / log / add / commit
  - 警惕：reset / rebase / amend
  - 危险：push --force / clean -f / branch -D
- 5.2 commit 边界：一次 commit 应该包含什么
- 5.3 何时该让 Agent 自动 push，何时该停下来等人
- 5.4 冲突处理：merge conflict 来了 Agent 该怎么办
- 5.5 demo 加 git：从分支创建到 commit，但 push 留人工触发

**反常识点**：Coding Agent 出问题往往不是写错代码，而是 git 上手太快——一个 `git reset --hard` 比一千行错代码还可怕。

---

### 06 工程化三件套：SubAgent、Skill、Hook

**核心问题**：从能跑的 demo 到可维护的系统，缺哪些工程化能力？

**主要小节**：
- 6.1 SubAgent 在代码场景的样子
  - Code Reviewer：独立 context，专门挑刺
  - Test Runner：跑测试 + 总结失败原因
  - Explorer：仓库探索专用，结果只交给主 Agent 一份摘要
- 6.2 Skill 在代码场景的样子
  - commit Skill：commit 边界 + message 风格
  - migration Skill：DB schema 变更流程
  - review Skill：PR review 时该看什么
- 6.3 Hook：自动 + 不失控
  - 写前确认：destructive 命令拦截
  - 完成后触发：lint / format / test
  - CI 中的权限模式
- 6.4 demo 加上 reviewer SubAgent + commit Skill + lint Hook

**反常识点**：Hook 是最被低估的工程化工具——它把"模型可能不该做的事"从 prompt 层移到代码层，可靠性高一个数量级。

---

### 07 Eval 与可观测性：做对了吗？跑偏了吗？

**核心问题**：Coding Agent 跑一万次，怎么知道质量稳定？跑偏了怎么定位？

**主要小节**：
- 7.1 Coding Agent eval 的难点：正确解不唯一，pass@k 不够
- 7.2 SWE-bench 的局限：模拟 issue ≠ 真实 issue
- 7.3 自定义 eval 三层：工具调用对不对、改的位置对不对、最终行为对不对
- 7.4 可观测性：trace 一次任务的全过程
  - 每次 LLM call 的 input / output
  - 每次工具调用
  - context 占用和增长曲线
- 7.5 用 trace 反推失败：是没找到文件、改错了、还是测试没跑对
- 7.6 demo 加上 trace 输出 + 一组小 eval

**反常识点**：trace 比 eval 更重要——eval 告诉你"成功率 60%"，trace 告诉你"为什么这一次失败"；前者用于发布决策，后者用于改进。

---

### 08 接进 GitHub 与人机边界

**核心问题**：把 demo 变成一个真的接 PR / issue 的 bot，需要哪几步？哪些事仍然不该让它干？

**主要小节**：
- 8.1 接进 GitHub 的三种姿势
  - Webhook 触发（issue 创建、PR review）
  - 手动 @ 触发
  - 定时巡检（autofix CI）
- 8.2 PR review 响应：人类评论 → Agent 调整 → 重新 push
- 8.3 CI 失败 autofix：什么时候自动修、什么时候等人
- 8.4 反模式清单
  - 大型重构（跨 50+ 文件）
  - 核心架构改动
  - 安全敏感改动（认证、加密、权限）
  - 没有测试覆盖的代码
- 8.5 人机协作的分工原则：Agent 做"枯燥但有标准"的部分，人做"模糊但要判断"的部分
- 8.6 demo 上线：把前面所有章节攒下来的能力接进 GitHub

**反常识点**：Coding Agent 真正的价值不是"自动写代码"，而是"自动做那些人不愿做的工程琐事"——code review、跑测试、写 commit message、修 lint。这些事人能做但不愿做，Agent 做正好。

---

## 推荐阅读路径

### 路径 A：从头到尾（推荐）

```
01 → 02 → 03 → 04 → 05 → 06 → 07 → 08
```

每篇基于前一篇，demo 一步步长大；第 08 章把前面所有能力接到 GitHub，闭环。

### 路径 B：按需跳入

- 想知道 **Coding Agent 为什么特殊** → 01
- 想搭一个**最小可用的** → 02 + 03
- 想让 Agent **会跑测试和 git** → 04 + 05
- 想做**工程化和可观测** → 06 + 07
- 想**接进 GitHub** → 08

---

## 和其他系列的关系

- **Agent 系列**：本系列默认你读完了 Agent 系列前 5 章，不重复"Agent 是什么"
- **Skill 系列**：第 06 章的 Skill 部分是 Skill 系列在代码场景的应用
- **Multi-Agent 系列（如果做）**：第 06 章的 SubAgent 部分会用到 Multi-Agent 的部分思想，但本系列只用"临时帮手"模式，不涉及完整的多 Agent 团队

建议先读 Agent 系列前 5 章 + Skill 系列前 2 章，再读本系列。

---

## 状态

> 草稿大纲。代码与正文待写。当前与《Multi-Agent 系统》并列为第四部备选。
