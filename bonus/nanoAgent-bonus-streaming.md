# 从零开始理解 Agent（番外篇）：Agent 思考时，用户在干等

> **「从零开始理解 Agent」系列番外** —— 七篇正文 + 前几篇番外，我们一直在讲 Agent 内部怎么运转。但有一个体验问题从第一篇就存在：Agent 调用 API 后，终端一片空白，用户不知道它是在思考还是卡死了。这篇讲怎么解决。

---

## 一、问题在哪：同步调用的体验瓶颈

第一篇的核心代码是这样的：

```python
response = client.chat.completions.create(
    model=MODEL, messages=messages, tools=TOOLS
)
```

这是一次同步调用——发出请求，等 LLM 生成完整响应，然后才返回。如果 LLM 思考了 8 秒，用户就盯着空白终端等 8 秒。

画一下时序：

```
用户提问
  │
  ▼
  ┌─────────────────────────┐
  │  等待... （空白，无反馈）  │  ← 用户焦虑区
  └─────────────────────────┘
  │
  ▼
一次性输出全部内容
```

而生产级 Agent 的体验是这样的：

```
用户提问
  │
  ▼
  thinking...
  contemplating...        ← spinner，让用户知道 Agent 在忙
  │
  ▼
  我来帮你看看这个目录...    ← 文字逐字出现
  │
  ▼
  [执行] find . -name "*.py"  ← 显示工具调用
  │
  ▼
  找到了 8 个文件，最大的是... ← 结果逐步呈现
```

差距就在中间那段"等待"——同步调用时它是空白的，流式输出时它是有内容的。

---

## 二、流式 API：一个参数的区别

把同步调用变成流式，只需要加一个参数：

```python
# 同步（第一篇的做法）
response = client.chat.completions.create(
    model=MODEL, messages=messages, tools=TOOLS
)
# 等几秒... 一次性拿到完整结果

# 流式
stream = client.chat.completions.create(
    model=MODEL, messages=messages, tools=TOOLS,
    stream=True  # ← 就这一个参数
)
# 立刻返回，逐 chunk 读取
for chunk in stream:
    # 每生成一个 token 就收到一个 chunk
    ...
```

加了 `stream=True` 之后，API 不再等 LLM 生成完整响应，而是每生成一个 token 就立刻推送一个 chunk。代码从"等完了再处理"变成"边收边处理"。

最简单的流式输出——逐字打印 LLM 的文字：

```python
for chunk in stream:
    delta = chunk.choices[0].delta

    # 如果这个 chunk 包含文字内容，立刻打印
    if delta.content:
        print(delta.content, end="", flush=True)

print()  # 结束后换行
```

`end=""` 让 `print` 不换行，`flush=True` 让字符立刻输出到终端而不是等缓冲区满。就这两个参数，用户就能看到文字逐字出现，而不是干等几秒后一次性弹出一大段。

---

## 三、难点：流式模式下的工具调用

文字的流式输出很简单，但 Agent 的核心是工具调用——`tool_calls`。这是流式输出的真正难点。

在同步模式下，`tool_calls` 是完整返回的：

```python
# 同步模式，一次性拿到完整的工具调用
message.tool_calls = [
    {
        "id": "call_abc123",
        "function": {
            "name": "execute_bash",
            "arguments": '{"command": "find . -name *.py"}'
        }
    }
]
```

但在流式模式下，工具调用是**分散在多个 chunk 里**逐步送达的：

```python
# chunk 1: 告诉你有一个工具调用，函数名的开头
delta.tool_calls = [{"index": 0, "id": "call_abc123",
                      "function": {"name": "execute", "arguments": ""}}]

# chunk 2: 函数名的剩余部分
delta.tool_calls = [{"index": 0,
                      "function": {"name": "_bash", "arguments": ""}}]

# chunk 3: 参数的一部分
delta.tool_calls = [{"index": 0,
                      "function": {"arguments": '{"comma'}}]

# chunk 4: 参数的剩余部分
delta.tool_calls = [{"index": 0,
                      "function": {"arguments": 'nd": "find . -name *.py"}'}}]
```

函数名是 `execute` + `_bash` 拼起来的，参数是 `{"comma` + `nd": "find . -name *.py"}` 拼起来的。你必须自己累积这些碎片，拼成完整的工具调用后才能执行。

拼接逻辑：

```python
def collect_stream(stream):
    """从流式 chunk 中收集完整的文字内容和工具调用"""
    content = ""
    tool_calls = {}  # index → {id, name, arguments}

    for chunk in stream:
        delta = chunk.choices[0].delta

        # 累积文字
        if delta.content:
            content += delta.content
            print(delta.content, end="", flush=True)  # 实时打印

        # 累积工具调用的碎片
        if delta.tool_calls:
            for tc in delta.tool_calls:
                idx = tc.index
                if idx not in tool_calls:
                    tool_calls[idx] = {
                        "id": tc.id or "",
                        "name": "",
                        "arguments": ""
                    }
                if tc.id:
                    tool_calls[idx]["id"] = tc.id
                if tc.function:
                    if tc.function.name:
                        tool_calls[idx]["name"] += tc.function.name
                    if tc.function.arguments:
                        tool_calls[idx]["arguments"] += tc.function.arguments

    if content:
        print()  # 换行

    # 把字典转成列表
    completed_calls = [
        {
            "id": tool_calls[idx]["id"],
            "type": "function",
            "function": {
                "name": tool_calls[idx]["name"],
                "arguments": tool_calls[idx]["arguments"]
            }
        }
        for idx in sorted(tool_calls.keys())
    ]

    return content, completed_calls
```

核心思路就一个：**用字典按 index 累积每个工具调用的碎片，全部 chunk 读完后拼成完整结构。** 拼完之后，后续的工具执行逻辑和第一篇完全一样——解析 JSON、调用函数、把结果放回 messages。

---

## 四、给用户看什么：状态反馈设计

有了流式文字和工具调用拼接之后，可以在 Agent 循环的每个阶段给用户不同的反馈。关键是在循环中加几行 `print`：

```python
for i in range(max_iterations):
    print(f"\n[轮次 {i+1}]", flush=True)

    # ... 流式调用 LLM，collect_stream 内部逐字打印 ...

    if not tool_calls:
        return content

    for tc in tool_calls:
        func = tc["function"]
        function_name = func["name"]
        function_args = json.loads(func["arguments"])

        print(f"  [工具] {function_name}", flush=True)
        print(f"  [执行中...]", flush=True)

        function_response = available_functions[function_name](**function_args)

        print(f"  [完成] 返回 {len(function_response)} 字符", flush=True)

        messages.append({"role": "tool", "tool_call_id": tc["id"],
                         "content": function_response})
```

现在用户在每个阶段都能看到正在发生什么：LLM 思考时看到文字逐字出现，决定调用工具时看到工具名，执行中看到状态提示，执行完看到返回结果的大小。没有任何一个阶段是空白的。

---

## 五、让 Agent 更像人：Spinner Verbs

上面的方案解决了"有反馈"的问题，但还有一段空白：**LLM 开始推理到返回第一个 token 之间的等待。** 这段时间可能有几秒，终端还是空的。

生产级编码 Agent 有一个有趣的做法：在等待时随机滚动一些动词——"pondering..."、"contemplating..."、"orchestrating..."——让用户感受到"它在忙"。

```python
import threading
import random
import sys

SPINNER_VERBS = [
    "pondering", "contemplating", "reasoning", "analyzing",
    "orchestrating", "synthesizing", "deliberating", "evaluating",
    "investigating", "formulating", "computing", "processing",
    # 搞怪的
    "discombobulating", "galumphing", "lollygagging",
    "flibbertigibbeting", "kerfuffling", "perambulating",
    "topsy-turvying", "hullabalooing", "cattywampusing",
]

class Spinner:
    """在等待时随机显示动词"""

    def __init__(self, interval=1.5):
        self.interval = interval
        self.running = False
        self.timer = None

    def _tick(self):
        if not self.running:
            return
        verb = random.choice(SPINNER_VERBS)
        # \r 回到行首，\033[K 清除到行末
        sys.stderr.write(f"\r\033[K  {verb}...")
        sys.stderr.flush()
        self.timer = threading.Timer(self.interval, self._tick)
        self.timer.daemon = True
        self.timer.start()

    def start(self):
        self.running = True
        self._tick()

    def stop(self):
        self.running = False
        if self.timer:
            self.timer.cancel()
        sys.stderr.write("\r\033[K")  # 清除 spinner 行
        sys.stderr.flush()
```

嵌入 Agent 循环：

```python
spinner = Spinner()

# LLM 调用前启动 spinner
spinner.start()

stream = client.chat.completions.create(
    model=MODEL, messages=messages, tools=TOOLS, stream=True
)

# 收到第一个 chunk 后停止 spinner
first_chunk = True
for chunk in stream:
    if first_chunk:
        spinner.stop()
        first_chunk = False
    # 正常处理 chunk...
```

效果是这样的：

```
用户: 帮我统计 Python 文件行数

  contemplating...        ← 每隔一两秒换一个
  orchestrating...
  galumphing...           ← 偶尔蹦出一个搞怪的
                          ← spinner 消失，文字开始出现
  我来帮你统计一下...       ← 流式文字接管
```

这个技巧背后有一个 UX 原则：**不确定的等待比确定的等待更让人焦虑。** 用户不知道要等多久时，任何动态反馈都比空白好。Spinner verbs 就是 Agent 版的"进度条"——它不告诉你还要多久，但它告诉你"我还活着，正在干活"。

搞怪的动词（"discombobulating"、"flibbertigibbeting"）不是必须的，但它们给 Agent 加了一点人格感。用户会觉得这个工具有"性格"，而不是一个冷冰冰的命令行。有些编码 Agent 内置了上百个 spinner verbs，从正经的到荒诞的都有。

---

## 六、工具输出也能流式吗

到目前为止，流式的是 LLM 的输出。但 Agent 还有另一个可能很慢的环节：**工具执行。**

第一篇用的是 `subprocess.run()`——等命令执行完，一次性拿回全部输出。如果命令是 `npm install`（可能跑几十秒）或 `pytest`（可能跑几分钟），用户又要面对一段空白。

`subprocess.Popen` 可以逐行读取命令的输出：

```python
import subprocess

def execute_bash_stream(command):
    """流式执行 bash 命令，逐行打印输出"""
    print(f"  $ {command}", flush=True)
    output_lines = []

    process = subprocess.Popen(
        command, shell=True,
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        text=True
    )

    for line in process.stdout:
        line = line.rstrip('\n')
        output_lines.append(line)
        print(f"    {line}", flush=True)  # 实时打印每一行

    process.wait()
    return '\n'.join(output_lines)
```

效果：

```
  [工具] execute_bash
  $ npm install
    added 1 package
    added 2 packages          ← 逐行出现，而不是等 30 秒后一次性弹出
    added 3 packages
    ...
    added 127 packages in 28s
  [完成] 返回 2340 字符
```

对于长时间运行的命令，这个改动的体验提升比 LLM 流式输出还大——因为工具执行的等待时间往往比 LLM 推理更长。

---

## 七、小结

回顾一下这篇番外加了什么：

| 改动 | 代码量 | 体验提升 |
|------|--------|---------|
| `stream=True` + 逐字打印 | 改 1 行，加几行 | LLM 思考时有文字输出 |
| 工具调用碎片拼接 | 约 30 行 | 流式和工具调用兼容 |
| 状态反馈（轮次、工具名、执行中） | 约 10 行 print | 每个阶段都有反馈 |
| Spinner verbs | 约 30 行 | 消除最后的空白等待 |
| 工具输出流式（Popen） | 改 1 个函数 | 长命令不再干等 |

全部加起来不到 100 行改动，但用户体验从"干等 → 一次性输出"变成了"全程有反馈"。

回到 Harness 番外篇的视角：流式输出和状态反馈是 Harness 面向用户的那一层。Token 追踪是给开发者看的，Eval 是给质量保障看的，而流式输出是给最终用户看的——让用户在 Agent 工作的每一刻都知道它在干什么。

---

*「从零开始理解 Agent」系列番外。前面的番外讲 Agent 内部怎么优化，这篇讲 Agent 外部怎么让用户不焦虑。*
