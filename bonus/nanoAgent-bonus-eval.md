# 从零开始理解 Agent（番外篇）：Agent 怎么知道自己做完了？

> **「从零开始理解 Agent」系列番外** —— 有读者问了一个好问题：第一篇里，Agent 循环的退出条件是"没有 tool_calls 就停"。但 LLM 不调工具，不代表任务完成了——它可能只是"懒了"。Agent 到底怎么判断任务**真正做完了**？

---

## 一、回顾第一篇的退出条件

第一篇的核心循环长这样：

```python
for _ in range(max_iterations):
    response = client.chat.completions.create(
        model=MODEL, messages=messages, tools=TOOLS
    )
    message = response.choices[0].message

    if not message.tool_calls:   # ← 退出条件：没有工具调用
        return message.content

    # 有工具调用，继续执行...
```

退出逻辑只有一行：`if not message.tool_calls`。

这意味着 Agent 的"完成判断"完全交给了 LLM——LLM 觉得不需要再调工具了，Agent 就停了。这在大多数情况下没问题：LLM 处理完所有步骤后，会自然地返回一段总结文字而不是工具调用，循环结束。

但这个机制有几个隐患：

- **LLM 提前放弃**：任务复杂时，LLM 可能在中间某步觉得"差不多了"就停下，实际并没有完成。
- **LLM 进入幻觉**：LLM 可能直接编造一个"结果"返回，而不是真正去执行。
- **`max_iterations` 耗尽**：循环次数用完了，Agent 被迫退出，不管做没做完。

这三种情况，Agent 自己都不知道自己"没做完"。

---

## 二、三层评估体系

解决"怎么知道做完了"的方法，可以按信任程度分成三层，每一层比上一层更可靠：

```
可靠性 ↑

Level 2：结构化断言（代码检查具体条件）
Level 1：LLM 自评（问一句"你完成了吗？"）
Level 0：无 tool_calls（第一篇的做法）    ← 当前
```

逐层来看。

---

## 三、Level 0：无 tool_calls（现状）

就是第一篇的做法，不再赘述。它的优点是零成本——不需要额外代码、不消耗额外 token。对于"帮我写个 hello world"这种简单任务，完全够用。

问题出在复杂任务上。当 Agent 需要执行十几步、调用多个工具时，"不调工具了"不等于"做完了"。

---

## 四、Level 1：LLM 自评

思路很简单：Agent 循环结束时，额外问 LLM 一句"任务完成了吗？"

```python
def check_completion(messages, task):
    """让 LLM 自我评估任务是否完成"""
    check_prompt = f"""原始任务：{task}

回顾上面的对话历史，判断任务是否已经完全完成。
只回答 YES 或 NO，然后简要说明理由。"""

    response = client.chat.completions.create(
        model=MODEL,
        messages=messages + [{"role": "user", "content": check_prompt}]
    )
    answer = response.choices[0].message.content
    return "YES" in answer.upper()
```

把它嵌入循环：

```python
for i in range(max_iterations):
    response = call_llm(messages)
    message = response.choices[0].message

    if not message.tool_calls:
        # 不是直接退出，而是先问一句
        if check_completion(messages, original_task):
            return message.content
        else:
            # 没完成，注入续写提示
            messages.append({
                "role": "user",
                "content": "任务还未完成，请继续执行。"
            })
            continue

    # 有工具调用，继续执行...
```

如果你读过 Harness 番外篇，会发现这就是 **Ralph Loop**——在退出点插入一个 Hook，拦截退出、检查完成度、没做完就续命。

**优点：** 实现简单，只需几行代码。对于"写一个文件"、"部署一个服务"这类任务，LLM 通常能准确判断是否完成。

**缺点：** LLM 评估 LLM，本质是"自己判自己的作业"。如果 LLM 对任务的理解就有偏差，自评也会跟着偏。而且每次自评要消耗额外 token。

---

## 五、Level 2：结构化断言

不靠 LLM 的主观判断，而是用代码检查客观条件。

比如任务是"创建一个 Python 项目，包含 main.py 和 test.py"，完成条件可以精确定义：

```python
def verify_task(task_type, params):
    """用代码检查任务是否真正完成"""

    if task_type == "create_project":
        checks = []
        for filename in params["required_files"]:
            exists = os.path.exists(filename)
            checks.append({"file": filename, "exists": exists})

        # 如果要求有测试文件，还要跑一下测试
        if params.get("run_tests"):
            result = subprocess.run(
                ["python", "-m", "pytest", params["test_dir"], "-q"],
                capture_output=True, text=True, timeout=30
            )
            checks.append({
                "tests": "passed" if result.returncode == 0 else "failed",
                "output": result.stdout[-200:]  # 只取最后 200 字符
            })

        all_passed = all(
            c.get("exists", True) and c.get("tests") != "failed"
            for c in checks
        )
        return all_passed, checks

    # 其他任务类型...
```

嵌入 Agent 循环的方式也变了——不是在"退出时"检查，而是在"每一步"之后都可以检查：

```python
for i in range(max_iterations):
    response = call_llm(messages)
    # ... 执行工具调用 ...

    # 每 N 轮检查一次，或在 Agent 说"完成了"时检查
    if should_verify(i, message):
        passed, details = verify_task(task_type, task_params)
        if passed:
            return format_result(message.content, details)
        else:
            # 把未通过的条件告诉 Agent
            feedback = format_verification_feedback(details)
            messages.append({
                "role": "user",
                "content": f"验证未通过：\n{feedback}\n请修复后继续。"
            })
```

**关键区别：** Level 1 是 LLM 说"我觉得完成了"，Level 2 是代码说"文件存在、测试通过、API 返回 200"。后者不可伪造。

**优点：** 结果可靠、可复现、零幻觉。

**缺点：** 需要提前定义"完成条件"，不同任务的断言逻辑不同，通用性差。适合标准化的任务（CI/CD 流水线、代码生成、文件操作），不适合开放性任务（"帮我写一篇博客"）。

---

## 六、三层怎么选？

选择的依据是**任务的风险等级和可验证性**：

| 场景 | 推荐层级 | 原因 |
|------|---------|------|
| 日常对话、简单问答 | Level 0 | 没有"完成"的概念，LLM 回答了就是回答了 |
| 写文件、改代码 | Level 1 | LLM 自评 + 人类最终确认，成本低 |
| CI/CD 流水线中的 Agent | Level 2 | 必须用代码断言，不能靠 LLM 说"我觉得没问题" |
| 高风险操作（数据库迁移、生产部署） | Level 2 + 人类审批 | 断言只是前置检查，最终决策权在人 |

实际工程中，三层经常混合使用。比如一个代码生成 Agent 可能这样工作：

1. 循环中用 **Level 0** 驱动基本流程（没有 tool_calls 就进入检查阶段）
2. 进入检查阶段后用 **Level 2** 跑测试（`pytest` 通过了才算完成）
3. 测试没过就用 **Level 1** 让 LLM 分析失败原因，注入反馈继续修复

---

## 七、回到第一篇

现在重新看第一篇的那行代码：

```python
if not message.tool_calls:
    return message.content
```

它不是"错的"——它是 Level 0，是最简单也最实用的退出条件。对于教学目的，它完美地展示了 Agent 循环的核心机制。

但如果你要把这个 Agent 用到真实场景，你需要在这行代码后面加一层检查。加哪一层，取决于你的任务有多重要、后果有多严重。

回顾 Harness 番外篇的定义：Harness 是模型周围的整套系统——工具、记忆、规划、安全、压缩，都是 Harness 的组成部分。Eval 也是。它负责的是 Harness 中"退出验证"这个环节：Agent 说做完了，Harness 来确认是不是真的做完了。

---

*「从零开始理解 Agent」系列番外。正文七篇讲 Agent 怎么跑，这篇讲 Agent 怎么知道自己跑对了。*
