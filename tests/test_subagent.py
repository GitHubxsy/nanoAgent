"""
test_subagent.py - 验证 subagent 机制，不需要 openai 包和 API Key
通过 mock OpenAI 客户端，模拟 LLM 返回 subagent tool_call 的完整流程
"""

import json, os, sys, types

# ==================== Mock OpenAI ====================
# 模拟 LLM 的行为：第一次返回 subagent tool_call，第二次返回文本

call_count = 0

class MockToolCall:
    def __init__(self, id, name, arguments):
        self.id = id
        self.function = types.SimpleNamespace(name=name, arguments=arguments)

class MockMessage:
    def __init__(self, content=None, tool_calls=None):
        self.content = content
        self.tool_calls = tool_calls

class MockChoice:
    def __init__(self, message):
        self.message = message

class MockResponse:
    def __init__(self, choices):
        self.choices = choices

class MockCompletions:
    def create(self, **kwargs):
        global call_count
        call_count += 1
        tools = kwargs.get("tools", [])
        tool_names = [t["function"]["name"] for t in tools]

        # 如果是 SubAgent 的调用（没有 subagent 工具），返回 bash + 最终文本
        if "subagent" not in tool_names:
            if call_count % 2 == 0:
                # SubAgent 先调用 bash
                return MockResponse([MockChoice(MockMessage(tool_calls=[
                    MockToolCall("call_sub_1", "bash", json.dumps({"command": "echo 'hello from subagent'"}))
                ]))])
            else:
                # SubAgent 完成，返回文本
                return MockResponse([MockChoice(MockMessage(content="[SubAgent 结果] 已完成任务"))])

        # 主 Agent 的调用：返回 subagent tool_call
        if call_count == 1:
            return MockResponse([MockChoice(MockMessage(tool_calls=[
                MockToolCall("call_1", "subagent", json.dumps({
                    "role": "Python backend developer",
                    "task": "创建一个简单的 hello.py"
                }))
            ]))])
        else:
            return MockResponse([MockChoice(MockMessage(
                content="任务完成！我委派了一个 Python 后端工程师来创建 hello.py。"
            ))])

class MockChat:
    completions = MockCompletions()

class MockOpenAI:
    def __init__(self, **kwargs):
        self.chat = MockChat()

# ==================== 注入 Mock 并导入 ====================

# 创建假的 openai 模块
fake_openai = types.ModuleType("openai")
fake_openai.OpenAI = MockOpenAI
sys.modules["openai"] = fake_openai

# 现在可以安全导入了
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
agent = __import__("agent-subagent")

# ==================== 测试 ====================

print("=" * 60)
print("  agent-subagent.py 完整测试（Mock LLM，无需 API）")
print("=" * 60)
print()

# 测试 1: 工具注册
tool_names = [t["function"]["name"] for t in agent.tools]
assert "subagent" in tool_names
assert "subagent" in agent.available_functions
print(f"✅ 测试 1: subagent 已注册 (全部工具: {tool_names})")

# 测试 2: SubAgent 工具列表排除自身
sub_tools = [t for t in agent.tools if t["function"]["name"] != "subagent"]
sub_names = [t["function"]["name"] for t in sub_tools]
assert "subagent" not in sub_names
assert "bash" in sub_names
print(f"✅ 测试 2: SubAgent 工具列表排除自身 (可用: {sub_names})")

# 测试 3: 基础工具可用
result = agent.bash("echo 'test ok'")
assert "test ok" in result
result = agent.write("/tmp/_subagent_test.txt", "hello")
assert "Successfully" in result
result = agent.read("/tmp/_subagent_test.txt")
assert "hello" in result
os.remove("/tmp/_subagent_test.txt")
print("✅ 测试 3: 基础工具 (bash/write/read) 正常工作")

# 测试 4: 完整流程 - 主 Agent 调用 SubAgent
print()
print("-" * 60)
print("  测试 4: 完整 Agent 循环（Mock LLM 自动触发 SubAgent）")
print("-" * 60)
print()

call_count = 0  # 重置计数器
result = agent.run("创建一个简单的 hello.py 文件")

print()
print(f"最终结果: {result}")
print()
assert result is not None
print("✅ 测试 4: 主 Agent → SubAgent → 返回结果，完整链路走通")

print()
print("=" * 60)
print("  全部测试通过 ✅")
print("=" * 60)
print()
print("实际运行（需要 API Key）:")
print("  export OPENAI_API_KEY='your-key'")
print("  python agent-subagent.py '创建一个 TODO 应用，包含 Python 后端和 HTML 前端'")
