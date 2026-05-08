# 从零开始做 Coding Agent（一）：和通用 Agent 的差别在哪

> **「从零开始做 Coding Agent」系列** —— 前三部讲"理解"，这一部讲"做"。我们围绕同一个 demo 项目（从一个 GitHub issue 出发，最终提一个能合并的 PR），从最小骨架开始，一章一章把它做成一个可托管的 Coding Agent。
>
> - **第一篇：和通用 Agent 的差别在哪**（本文）
> - 第二篇：最小骨架：Read / Edit / Bash 跑通一次修改（即将更新）
> - 第三篇：代码上下文工程（即将更新）
> - 第四篇：红绿循环与自我验证（即将更新）
> - 第五篇：让 Agent 学会用 git（即将更新）
> - 第六篇：工程化三件套：SubAgent、Skill、Hook（即将更新）
> - 第七篇：Eval 与可观测性（即将更新）
> - 第八篇：接进 GitHub 与人机边界（即将更新）

---

## 开场：一次失败的修 bug

假设你已经读完了 [Agent 系列前几篇](../../agent/README.md)，手里有一个会用工具的通用 Agent——能读文件、跑命令、写文件，三百多行 Python，干净利落。

现在你给它一个真实任务：

> "项目根目录下的 `app/login.py` 有个 race condition，两个并发请求会让 session 被错误地共享。帮我修一下。"

它开始干活：

```text
> read_file("app/login.py")          ✓
> read_file("app/__init__.py")       ✓
> read_file("app/session.py")        ✓
> read_file("app/middleware.py")     ✓
> read_file("app/config.py")         ✓
> read_file("app/utils.py")          ✓
> ... 又读了 14 个文件 ...
> ✗ 上下文超过 100K，请求被截断
```

或者它换个姿势翻车：

```text
> write_file("app/login.py", "...重写后的整个文件...")  ✓
> bash("git add -A")                                    ✓
> bash("git commit -m 'fix bug'")                       ✓
> bash("git push")                                      ✓
```

你打开看，文件确实改了。但同时——它还顺手"清理了一下" import 顺序，删掉了一个看起来"没用"的 helper（其实另一个文件在用），然后 commit 名是含糊的 `fix bug`，最后还自动 push 了。

CI 红了。

---

这就是为什么 **Coding Agent 不是"通用 Agent + 几个文件操作工具"**。

通用 Agent 的能力命题是"能调工具完成任务"。
Coding Agent 的能力命题是"能调工具完成代码任务**而且不闯祸**"。

这是两个完全不同的工程问题。

---

## 一、通用 Agent + 工具 ≠ Coding Agent

把 Read / Bash / Write 这三个工具塞进通用 Agent，它能做最简单的代码任务——"在 hello.py 里加一行 print"是没问题的。但任务复杂一点，它就会在四个地方系统性翻车：

1. **找不到该改的文件**：仓库稍微大一点，它要么"读所有文件"爆 context，要么瞎猜
2. **改的方式太粗暴**：要么整文件重写、要么乱猜 search-replace，每次都改坏一点
3. **不知道自己改对没**：改完就说"完成了"，从不跑测试也不验证
4. **git 上手太快**：自动 commit 自动 push，一旦改错没法挽回

每一个问题单独看都好像"再加一个工具就解决了"。但合到一起，就是 Coding Agent 这一类工具存在的根本原因——它**不是更花哨的通用 Agent，而是结构上为代码场景做了刻意约束的 Agent**。

接下来把这四个翻车点反过来，就是 Coding Agent 区别于通用 Agent 的四个核心特殊性。

---

## 二、四个特殊性

### 特殊性 1：仓库感知（Repository Awareness）

通用 Agent 看到的是文件——一个一个独立的文件。
Coding Agent 看到的必须是**仓库**——文件、符号、依赖、测试、构建产物之间有关系。

具体表现：

- 知道 `tests/` 和 `src/` 的对应关系
- 知道 `package.json` / `pyproject.toml` 是入口
- 知道哪些目录是构建产物（`node_modules/`、`__pycache__/`、`dist/`），不该读不该改
- 知道 `CLAUDE.md` / `AGENTS.md` 这种指引文件应该优先读
- 知道 `.gitignore` 里的东西不属于"项目"

**反例**：通用 Agent 接到"修 race condition"的任务，它可能从根目录 `ls -R`，把 `node_modules/` 里 8 万个 JS 文件也列了一遍——context 就这么爆了。

仓库感知不是模型的"先验知识"，而是**工具与提示词共同建立的工程约束**：grep 默认排除 `.gitignore`、Read 拒绝过大文件、提示词里告诉模型"先看 README"。这些约束写在哪里、怎么写，是后面几章的内容。

### 特殊性 2：动作可逆性（Reversibility）

通用 Agent 的工具默认都是"做了就做了"。
Coding Agent 必须把每个动作按可逆性分级：

| 动作 | 可逆性 | 兜底机制 |
|------|--------|----------|
| Read 文件 | 完全可逆 | 没有副作用 |
| Edit 文件 | 半可逆 | 有 git 兜底，但 dirty 改动可能丢失 |
| `git commit` | 半可逆 | `git reset` 能回退，**前提是没 push** |
| `git push` | 不可逆 | 公开历史，可能已被别人 pull |
| `git push --force` | 极度危险 | 可能覆盖别人的工作 |
| `rm -rf` | 完全不可逆 | 没救 |

通用 Agent 不需要这种分级——它给客户写邮件，发出去就是发出去了，不需要再细分。但 Coding Agent 如果不分级，**第一次"自动 push --force"就够让用户再也不敢用**。

可逆性这件事，是后面第 02 章 Edit 工具语义之争和第 05 章 git 单独成章的根本原因。

### 特殊性 3：测试闭环（Verification Loop）

通用 Agent 做完一个任务，最后一句话往往是"任务已完成"。
Coding Agent **不能信任自己的"完成"**——它必须有一个外部回路来验证。

幸运的是，代码场景的回路天然存在：

- 单元测试：跑了红绿就知道
- 类型检查：编译过就是过
- Lint：错了有报错
- UI 验证：启 dev server，用浏览器看一眼或者跑 Playwright 截图

通用 Agent 的回路要靠人来反馈（"这封邮件写得不对"），Coding Agent 的回路可以靠机器自己跑。

这本来是 Coding Agent **比通用 Agent 更容易做好**的部分——只要你愿意把这个回路接上。

但很多 Coding Agent 实现把这部分省了。它们让模型自己说"我修好了"——而模型，你猜怎么着，特别擅长说自己修好了。

### 特殊性 4：长任务一致性（Long-Task Coherence）

通用 Agent 的任务往往"一发即终"——查个天气、写封邮件，几分钟搞定。
Coding Agent 的任务经常"半小时起步"——理解仓库、改 5 个文件、跑 3 轮测试、回应 review 评论、再改 2 个文件。

这意味着：

- 上下文会膨胀到几十 K 甚至上百 K
- 中间需要 compact / 摘要
- 子任务之间需要保持目标一致（不要"修着修着改成重构了"）
- 出错需要能从中间状态恢复

这是为什么 Coding Agent 必须配上 SubAgent / Skill / 上下文压缩这些工程化能力——**不是为了高级，是为了在长任务里不跑偏**。

---

## 三、为什么"老三样"赢了

回看市面上能用的 Coding Agent——Claude Code、Cursor、Aider、Continue——它们的工具集惊人地相似：

```text
Read    读文件
Edit    精确字符串替换
Bash    跑命令（包括 git、跑测试、启服务）
Grep    全文搜索
Glob    文件匹配
```

就这五样，覆盖了 95% 的代码任务。

曾经有人尝试过更"高级"的工具：

- 提供 IDE-like 的 AST 操作工具（"重命名这个变量"、"提取这个方法"）
- 提供 LSP-based 的语义跳转工具
- 提供专门的 patch 工具，让 LLM 直接生成 unified diff

这些尝试普遍输给了"老三样"。原因有三：

**1. 老三样的语义对模型最透明。**

LLM 训练数据里见过几亿次 `cat file.py` 和 `grep foo`，它对这些工具的理解几乎是肌肉记忆。但它没见过几次 `ast.rename_symbol("foo", "bar")`，每次都要现学，错误率高一个量级。

**2. 老三样的可逆性最容易做。**

Edit 工具有两个"啰嗦"的约束：必须先 Read 才能 Edit、改的内容必须精确匹配。这两个约束把整个 Coding Agent 的可逆性根基钉死了——LLM 永远只能改"它看过的内容"，而不能凭幻觉改。AST / LSP 工具的副作用更复杂，回滚成本更高。

**3. 老三样的失败模式最少。**

Read / Edit / Bash 出错的形式只有三种：文件不存在、字符串不匹配、命令退出非零。AST 工具的失败模式可以列十几种，每一种都需要 LLM 单独学会处理。

---

这是 Coding Agent 设计中最重要的一个反常识点：

**当我们想"让 Coding Agent 更聪明"时，往往要做的不是给它更高级的工具，而是给它更原始、更稳定、可逆性更好的工具。**

模型本身已经够聪明。它需要的不是 IDE 的能力，而是 IDE 没有的"必须先看过才能改"的纪律。

---

## 四、本系列的 demo

接下来 7 章，我们围绕一个具体的 demo 项目，从零做一个 Coding Agent。

**最终目标**：从一个 GitHub issue 出发——

> **Issue #42**: 登录页有 race condition，两个并发请求会让 session 错乱。
> 复现：开两个浏览器窗口同时登录，session 偶尔会串。

到一个能合并的 PR——

> **PR #43**: Fix race condition in login session handling
> - `app/login.py`: 加锁保护 session 创建
> - `tests/test_login.py`: 增加并发测试用例
> - CI 通过（pytest + Playwright）

每一章的 demo 进度：

| 章 | demo 状态 |
|----|----------|
| 02 | MVP：Read / Edit / Bash 跑通"改一行修单测" |
| 03 | 加上下文工程，能自己定位 bug 所在文件 |
| 04 | 加测试循环 + UI 验证 |
| 05 | 加 git，能产出可 review 的 commit |
| 06 | 加 SubAgent / Skill / Hook，工程化骨架成型 |
| 07 | 加 trace 和 eval |
| 08 | 接到 GitHub Actions，真的能在自己的仓库里跑 |

我们不会用任何现成的 Coding Agent 框架——LangChain、Aider、Codex 都不用。每一行核心逻辑都自己写，目标是让你看清楚每一个设计选择**为什么是这样**。

代码会维持在能读完的规模：每一章的核心 Python 文件都不超过 300 行，最终完整版控制在 1000 行以内。

---

## 一句话总结

通用 Agent 的核心命题是"会调工具"，Coding Agent 的核心命题是"调工具时不闯祸"。

让 Coding Agent 能用的不是更强的模型，而是这四个特殊性：**仓库感知 + 动作可逆 + 测试闭环 + 长任务一致**。模型再强，这四样不到位就是个"敢上手的菜鸟"；模型再弱，这四样齐了就是个"靠谱的小工"。

---

## 下一篇预告

第一章我们建立了直觉：Coding Agent 是个"被刻意约束的 Agent"。下一篇就开始动手——用 Read / Edit / Bash 三件套写一个约 150 行的 `nano-cc`，跑通最简单的修单测任务。

但写之前要先回答一个绕不开的问题：Edit 工具到底应该长什么样？

市面上至少有四种主流设计——整文件重写、search-replace、diff-apply、exact-string——它们看起来都"差不多能用"，但失败模式完全不同。第二篇会把这四种摆在一起对比，讲清楚为什么 Claude Code / Cursor / Aider 最后都收敛到 exact-string 这一种。

---

*「从零开始做 Coding Agent」系列建立在 [从零开始理解 Agent](../../agent/README.md) 之上。如果你还不熟悉"Agent = LLM + 工具 + 循环"这个最小闭环，建议先读完 Agent 系列前 5 章再来读本系列。*
