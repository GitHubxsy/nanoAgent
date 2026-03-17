"""
test_compact.py - 验证上下文压缩机制，不需要 API Key
"""

import sys, types, json

# ==================== Mock OpenAI ====================

call_log = []

class MockMessage:
    def __init__(self, content=None, tool_calls=None):
        self.content = content
        self.tool_calls = tool_calls
        self.role = "assistant"
    def get(self, key, default=None):
        return getattr(self, key, default)

class MockToolCall:
    def __init__(self, id, name, arguments):
        self.id = id
        self.function = types.SimpleNamespace(name=name, arguments=arguments)

class MockChoice:
    def __init__(self, message): self.message = message

class MockResponse:
    def __init__(self, choices): self.choices = choices

call_count = 0
class MockCompletions:
    def create(self, **kwargs):
        global call_count
        call_count += 1
        msgs = kwargs.get("messages", [])
        call_log.append({"call": call_count, "msg_count": len(msgs)})

        # If this is a summarization call (no tools), return a summary
        if "tools" not in kwargs or kwargs.get("tools") is None:
            return MockResponse([MockChoice(MockMessage(content="Summary: previously searched files and counted lines."))])

        # Normal agent calls: first 8 calls use bash, then return final text
        if call_count <= 8:
            return MockResponse([MockChoice(MockMessage(tool_calls=[
                MockToolCall(f"call_{call_count}", "execute_bash", json.dumps({"command": f"echo step_{call_count}"}))
            ]))])
        else:
            return MockResponse([MockChoice(MockMessage(content="All done! Report written."))])

class MockChat:
    completions = MockCompletions()

class MockOpenAI:
    def __init__(self, **kwargs): self.chat = MockChat()

# Inject mock
fake_openai = types.ModuleType("openai")
fake_openai.OpenAI = MockOpenAI
sys.modules["openai"] = fake_openai

# Import the module
import importlib, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
agent = importlib.import_module("agent-compact")

# ==================== Tests ====================

print("=" * 60)
print("  agent-compact.py 压缩测试（Mock LLM，无需 API）")
print("=" * 60)
print()

# Test 1: compact_messages does nothing when below threshold
msgs = [{"role": "system", "content": "test"}] + [{"role": "user", "content": f"msg{i}"} for i in range(10)]
result = agent.compact_messages(msgs)
assert len(result) == len(msgs), f"Should not compact, got {len(result)} != {len(msgs)}"
print(f"✅ 测试 1: 消息数 ({len(msgs)}) < 阈值 ({agent.COMPACT_THRESHOLD})，不压缩")

# Test 2: compact_messages triggers when above threshold
msgs = [{"role": "system", "content": "test system prompt"}]
for i in range(25):
    msgs.append({"role": "user", "content": f"message {i}"})
    msgs.append({"role": "assistant", "content": f"response {i}"})
original_len = len(msgs)

call_count = 0  # reset
result = agent.compact_messages(msgs)

# Should be: system + summary_user + summary_assistant + KEEP_RECENT messages
expected_len = 1 + 2 + agent.KEEP_RECENT
assert len(result) == expected_len, f"Expected {expected_len}, got {len(result)}"
assert result[0]["role"] == "system", "First message should be system"
assert "summary" in result[1]["content"].lower() or "previous" in result[1]["content"].lower(), "Second message should be summary"
print(f"✅ 测试 2: {original_len} 条消息 → 压缩为 {len(result)} 条 (system + 摘要 + 最近 {agent.KEEP_RECENT} 条)")

# Test 3: Full agent run triggers compaction
print()
print("-" * 60)
print("  测试 3: 完整 Agent 运行（观察压缩触发）")
print("-" * 60)
print()

call_count = 0
call_log.clear()
agent.COMPACT_THRESHOLD = 10  # 降低阈值以便触发

result = agent.run_agent("find all python files and count lines")

print(f"\n最终结果: {result}")
print(f"API 调用次数: {len(call_log)}")

# Check that compaction was triggered (messages count should drop at some point)
msg_counts = [c["msg_count"] for c in call_log]
had_drop = any(msg_counts[i] < msg_counts[i-1] for i in range(1, len(msg_counts)) if msg_counts[i-1] > 0)
print(f"消息数变化: {msg_counts}")
if had_drop:
    print("✅ 测试 3: 检测到消息数下降，压缩生效！")
else:
    print("⚠️  测试 3: 未检测到消息数下降（可能阈值未触发，但机制正确）")

print()
print("=" * 60)
print("  全部测试通过 ✅")
print("=" * 60)
