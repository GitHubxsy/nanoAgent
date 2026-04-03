# 从零开始理解 Agent（番外篇）：LLM 是怎么从一堆工具里挑出正确的那个的？

> 这是「从零开始理解 Agent」系列的一篇番外。有读者问了一个好问题：Agent 有那么多工具（bash、read、write、grep、subagent……），LLM 是怎么知道该调用哪一个的？

---

## 先说结论

**LLM 不是"选择"工具，而是"生成"工具调用。**

听起来像文字游戏，但区别很大。我们来拆解。

---

## 一、LLM 看到了什么？

每次调用 API 时，你的代码会把两样东西一起发给 LLM：

```python
response = client.chat.completions.create(
    model=MODEL,
    messages=messages,   # 1. 对话历史（用户任务 + 之前的对话）
    tools=tools          # 2. 所有工具的说明书列表
)
```

`tools` 就是一个 JSON 数组，里面每个工具长这样：

```json
{
  "name": "execute_bash",
  "description": "Execute a bash command on the system",
  "parameters": {
    "properties": {
      "command": {"type": "string", "description": "The bash command to execute"}
    },
    "required": ["command"]
  }
}
```

**所有工具的说明书在每次 API 调用时都会完整发送给 LLM。** 不是发一次就记住了，而是每次都带上。LLM 没有持久记忆——这一点在系列第二篇中讲过。

---

## 二、LLM 怎么"挑"的？

LLM 收到的信息是：

- **当前任务**："帮我统计当前目录下有多少个 Python 文件"
- **工具清单**：execute_bash（执行命令）、read_file（读文件）、write_file（写文件）、subagent（委派子任务）……

然后 LLM 做了一件事，和你做阅读理解时完全一样——**读题、看选项、选最匹配的。**

它的"推理"过程大概是这样的（虽然我们看不到内部思考，但效果等价于）：

```
任务：统计 Python 文件数量
      → 需要在文件系统中搜索
      → 搜索文件最直接的方式是执行 shell 命令
      → 看一眼工具清单... execute_bash 的描述是"Execute a bash command"
      → 匹配！

决定：调用 execute_bash
参数：command = "find . -name '*.py' | wc -l"
```

然后 LLM 输出一段 JSON：

```json
{
  "tool_calls": [{
    "function": {
      "name": "execute_bash",
      "arguments": "{\"command\": \"find . -name '*.py' | wc -l\"}"
    }
  }]
}
```

**注意：LLM 输出的是文本（JSON 格式的文本）。** 它不是在"调用"什么函数，它只是在"说"——"我觉得应该调用 execute_bash，参数是这个"。真正的执行发生在你的 Python 代码里：

```python
result = available_functions["execute_bash"](command="find . -name '*.py' | wc -l")
```

这就是系列第一篇反复强调的：**LLM 是大脑，代码是手脚。LLM 输出意图，代码执行动作。**

---

## 三、所以"选工具"的本质是什么？

是**自然语言匹配**。

LLM 把用户的任务描述和每个工具的 `description` 做语义匹配，选出最相关的那个。这和 LLM 做"阅读理解"用的是同一个能力——给一段上下文和一个问题，输出最匹配的答案。

这也意味着：**工具的 description 写得好不好，直接决定了 LLM 选得准不准。**

比较一下：

```json
// ❌ 描述太模糊
{"name": "tool1", "description": "A useful tool"}

// ✅ 描述清晰准确
{"name": "execute_bash", "description": "Execute a bash command on the system. Use for running shell commands, installing packages, file operations, etc."}
```

第一个描述，LLM 根本不知道什么时候该用它。第二个描述，LLM 能精准判断"需要执行命令 → 用 execute_bash"。

**这也是为什么 Skill 那么重要。** Skill 不是给 LLM 新的能力，而是给它更好的判断依据——遇到"生成 Word 文档"的任务时，不是让 LLM 自己猜用什么库，而是通过 Skill 告诉它"用 docx 库，按这些步骤来"。

---

## 四、工具太多了怎么办？

如果你只有 6、7 个工具，全部塞进 `tools` 参数问题不大。但如果有几十甚至上百个工具呢？

两个问题会出现：

**1. Token 浪费。** 每个工具的 JSON Schema 大概占几百 token。50 个工具就是上万 token，还没开始干活就花掉了一大截上下文窗口。

**2. LLM 会"选花眼"。** 工具越多，描述越相似的工具越多，LLM 选错的概率就越高。就像你面前摆了 100 把螺丝刀，有十字的、一字的、六角的、内六角的、加长的、短柄的——你盯着看半天也不一定选对。

生产级 Agent 的解决方案叫**工具渐进加载**（也是 Harness 的一部分）：

```
第 1 轮：只给 LLM 最常用的 5 个基础工具
  → LLM 发现不够用，请求加载更多
第 2 轮：根据任务类型，动态加载相关的 Skill 工具
  → 比如检测到任务涉及 Docker，就加载 docker 相关工具
第 3 轮：继续执行
```

**不是一次性把所有工具都塞进去，而是按需加载。** 这样既省 token，又提高选择准确率。

---

## 五、一句话总结

LLM 选工具的过程 = **读任务描述 + 读工具说明书 + 语义匹配 + 输出 JSON**。

没有什么特殊的"工具选择算法"，就是自然语言理解能力的一个应用。所以：

- **工具的 description 写得好** → LLM 选得准
- **工具数量控制得当** → LLM 不会选花眼
- **Skill 提供额外指导** → LLM 不光选对工具，还知道怎么用好

理解了这一点，你就理解了为什么 Agent 领域有一句话：**工具的好坏不取决于实现多复杂，取决于说明书写得多清楚。**

---

*本文是「从零开始理解 Agent」系列的番外篇。完整系列见 [GitHub 仓库](https://github.com/GitHubxsy/nanoAgent)。*
