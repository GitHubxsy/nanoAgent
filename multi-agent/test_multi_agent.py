"""
multi-agent 系列测试套件
测试所有纯逻辑（mock 工具、共享状态、重试、trace、并行隔离等）。
LLM 调用均 mock，不消耗 API 额度。

运行：
    cd /Users/wendy/Desktop/nanoAgent
    python -m pytest multi-agent/test_multi_agent.py -v
"""

import importlib.util
import json
import sys
import threading
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

BASE = Path(__file__).parent


# ── 公共帮助函数 ──────────────────────────────────────────────────────────────

def load_module(chapter: str, filename: str):
    """在 patch openai 的前提下加载指定章节的模块。"""
    path = BASE / chapter / filename
    spec = importlib.util.spec_from_file_location(filename[:-3], path)
    mod = importlib.util.module_from_spec(spec)
    with patch("openai.OpenAI"):
        spec.loader.exec_module(mod)
    return mod


# ── 第一章：单 Agent baseline ─────────────────────────────────────────────────

class TestCh01MockTools:
    @pytest.fixture(scope="class")
    def mod(self):
        return load_module("01-when-single-agent-fails",
                           "multi-agent-01-when-single-agent-fails.py")

    def test_web_search_hit(self, mod):
        results = json.loads(mod.web_search("FlashAttention benchmark"))
        assert len(results) >= 1
        assert results[0]["url"] == "https://example.com/fa3"

    def test_web_search_pagedattention(self, mod):
        results = json.loads(mod.web_search("PagedAttention vLLM"))
        assert any("pa" in r["url"] for r in results)

    def test_web_search_no_match(self, mod):
        results = json.loads(mod.web_search("quantum computing"))
        assert results == []

    def test_web_read_known_url(self, mod):
        content = mod.web_read("https://example.com/fa3")
        assert "FlashAttention" in content
        assert len(content) <= 30000  # 受限制

    def test_web_read_unknown_url(self, mod):
        content = mod.web_read("https://example.com/nothere")
        assert "未找到" in content

    def test_write_file(self, mod, tmp_path):
        p = str(tmp_path / "out.md")
        result = mod.write_file(p, "hello agent")
        assert "Wrote" in result
        assert Path(p).read_text() == "hello agent"

    def test_write_file_creates_dirs(self, mod, tmp_path):
        p = str(tmp_path / "subdir" / "out.md")
        mod.write_file(p, "content")
        assert Path(p).exists()

    def test_all_mock_search_urls_in_mock_page_db(self, mod):
        """MOCK_SEARCH_DB 中所有 URL 都应能在 MOCK_PAGE_DB 里找到。"""
        for topic, results in mod.MOCK_SEARCH_DB.items():
            for r in results:
                assert r["url"] in mod.MOCK_PAGE_DB, (
                    f"ch01: URL '{r['url']}' (topic={topic}) 不在 MOCK_PAGE_DB"
                )


# ── 第二章：最小骨架 ──────────────────────────────────────────────────────────

class TestCh02MockTools:
    @pytest.fixture(scope="class")
    def mod(self):
        return load_module("02-minimum-skeleton",
                           "multi-agent-02-minimum-skeleton.py")

    def test_web_search_hit(self, mod):
        results = json.loads(mod.web_search("FlashAttention"))
        assert results[0]["title"] == "FA3"

    def test_web_search_sglang(self, mod):
        results = json.loads(mod.web_search("SGLang radix"))
        assert results[0]["url"] == "https://example.com/sglang"

    def test_web_search_miss(self, mod):
        assert mod.web_search("unknown topic xyz") == "[]"

    def test_web_read_hit(self, mod):
        content = mod.web_read("https://example.com/fa3")
        assert len(content) > 10
        assert "not found" not in content.lower()

    def test_web_read_miss(self, mod):
        content = mod.web_read("https://example.com/nonexistent")
        assert "not found" in content.lower()

    def test_mock_page_db_covers_all_search_urls(self, mod):
        """ch02: MOCK_SEARCH_DB 里的 URL 必须都在 MOCK_PAGE_DB 里。"""
        for topic, results in mod.MOCK_SEARCH_DB.items():
            for r in results:
                assert r["url"] in mod.MOCK_PAGE_DB, (
                    f"ch02: '{r['url']}' (topic={topic}) 不在 MOCK_PAGE_DB"
                )


# ── 第三章：通信方式 ──────────────────────────────────────────────────────────

class TestCh03SharedState:
    @pytest.fixture(scope="class")
    def mod(self):
        return load_module("03-communication",
                           "multi-agent-03-communication.py")

    def test_claim_first_succeeds(self, mod):
        state = mod.SharedState()
        assert state.claim("topic-A") is True

    def test_claim_duplicate_fails(self, mod):
        state = mod.SharedState()
        state.claim("topic-A")
        assert state.claim("topic-A") is False

    def test_claim_different_topics(self, mod):
        state = mod.SharedState()
        assert state.claim("topic-A") is True
        assert state.claim("topic-B") is True
        assert len(state.claimed_topics) == 2

    def test_url_fetch_lifecycle(self, mod):
        state = mod.SharedState()
        url = "https://example.com/fa3"
        assert state.is_url_fetched(url) is False
        state.record_url(url)
        assert state.is_url_fetched(url) is True

    def test_error_recording(self, mod):
        state = mod.SharedState()
        state.record_error("topic-X", "timeout after 30s")
        assert state.errors["topic-X"] == "timeout after 30s"

    def test_thread_safety_claim(self, mod):
        """并发 claim 同一 topic：只有一个线程应成功。"""
        state = mod.SharedState()
        results = []
        lock = threading.Lock()

        def try_claim():
            r = state.claim("shared-topic")
            with lock:
                results.append(r)

        threads = [threading.Thread(target=try_claim) for _ in range(20)]
        for t in threads: t.start()
        for t in threads: t.join()
        assert results.count(True) == 1
        assert results.count(False) == 19

    def test_web_search_returns_list(self, mod):
        results = json.loads(mod.web_search("FlashAttention"))
        assert isinstance(results, list)
        assert len(results) > 0

    def test_web_read_with_dedup_writes_file(self, mod, tmp_path):
        state = mod.SharedState()
        raw_path = tmp_path / "fa3.md"
        content = mod.web_read_with_dedup("https://example.com/fa3", state, raw_path)
        assert "FlashAttention" in content
        assert state.is_url_fetched("https://example.com/fa3")
        assert raw_path.exists()

    def test_web_read_with_dedup_uses_cache(self, mod, tmp_path):
        state = mod.SharedState()
        raw_path = tmp_path / "fa3.md"
        mod.web_read_with_dedup("https://example.com/fa3", state, raw_path)
        content2 = mod.web_read_with_dedup("https://example.com/fa3", state, raw_path)
        assert "[from cache]" in content2

    def test_searcher_tools_have_description(self, mod):
        """ch03 searcher() 内部的 tools 列表应包含 description 字段。"""
        src = (BASE / "03-communication" / "multi-agent-03-communication.py").read_text()
        searcher_section = src[src.index("def searcher"):]
        tools_start = searcher_section.index("tools = [")
        tools_end = searcher_section.index("]", tools_start) + 1
        tools_text = searcher_section[tools_start:tools_end]
        assert '"description"' in tools_text, (
            "ch03 searcher tools 缺少 description 字段"
        )


# ── 第四章：编排模式 ──────────────────────────────────────────────────────────

class TestCh04Orchestration:
    @pytest.fixture(scope="class")
    def mod(self):
        return load_module("04-orchestration",
                           "multi-agent-04-orchestration.py")

    def test_modes_dict_complete(self, mod):
        """四种编排模式必须都注册。"""
        assert set(mod.MODES.keys()) == {"workflow", "supervisor", "swarm", "hybrid"}

    def test_web_search_sglang(self, mod):
        results = json.loads(mod.web_search("SGLang"))
        assert results[0]["title"] == "SGLang"

    def test_web_search_vllm(self, mod):
        results = json.loads(mod.web_search("vLLM throughput"))
        assert results[0]["title"] == "vLLM"

    def test_web_search_miss(self, mod):
        assert mod.web_search("totally unknown") == "[]"

    def test_web_read_sglang_ok(self, mod):
        content = mod.web_read("https://example.com/sglang")
        assert "SGLang" in content

    def test_web_read_vllm_ok(self, mod):
        content = mod.web_read("https://example.com/vllm")
        assert "vLLM" in content

    def test_all_mock_search_urls_in_mock_pages(self, mod):
        """ch04: MOCK_SEARCH 中所有 URL 都必须存在于 MOCK_PAGES（修复验证）。"""
        mismatched = []
        for topic, results in mod.MOCK_SEARCH.items():
            url = results[0]["url"]
            if url not in mod.MOCK_PAGES:
                mismatched.append((topic, url))
        assert mismatched == [], (
            f"以下 topic 的 URL 在 MOCK_PAGES 中找不到：{mismatched}"
        )

    def test_web_read_returns_content_for_all_search_urls(self, mod):
        """ch04: 每个 topic 的搜索 URL 都能读到实际内容。"""
        for topic, results in mod.MOCK_SEARCH.items():
            url = results[0]["url"]
            content = mod.web_read(url)
            assert "not found" not in content.lower(), (
                f"topic={topic}, url={url} 返回 not found"
            )


# ── 第五章：状态与记忆 ────────────────────────────────────────────────────────

class TestCh05Scratchpad:
    @pytest.fixture(scope="class")
    def mod(self):
        return load_module("05-state-memory",
                           "multi-agent-05-state-memory.py")

    def test_claim_first(self, mod):
        sp = mod.Scratchpad()
        assert sp.claim("topic-A") is True

    def test_claim_duplicate(self, mod):
        sp = mod.Scratchpad()
        sp.claim("topic-A")
        assert sp.claim("topic-A") is False

    def test_url_fetch_tracking(self, mod):
        sp = mod.Scratchpad()
        url = "https://example.com/fa3"
        assert sp.is_fetched(url) is False
        sp.record_url(url)
        assert sp.is_fetched(url) is True

    def test_add_finding_and_snapshot(self, mod):
        sp = mod.Scratchpad()
        sp.add_finding("FlashAttention", "1.5x faster on H100", "https://example.com/fa3")
        sp.add_finding("FlashAttention", "uses async Tensor Cores", "https://example.com/fa3")
        snap = sp.snapshot_for_writer()
        findings = snap["key_findings"]["FlashAttention"]
        assert len(findings) == 2
        assert findings[0]["claim"] == "1.5x faster on H100"

    def test_add_conflict(self, mod):
        sp = mod.Scratchpad()
        sp.add_conflict({
            "a": "FlashAttention is faster",
            "b": "PagedAttention is faster",
            "why_conflict": "opposite speed claims"
        })
        snap = sp.snapshot_for_writer()
        assert len(snap["conflicts"]) == 1

    def test_snapshot_is_shallow_copy(self, mod):
        """向 snapshot 的顶层 dict 添加 key 不影响原始 scratchpad。"""
        sp = mod.Scratchpad()
        sp.add_finding("topic-X", "claim", "src")
        snap = sp.snapshot_for_writer()
        snap["key_findings"]["injected"] = []
        assert "injected" not in sp.key_findings

    def test_thread_safety_claim(self, mod):
        sp = mod.Scratchpad()
        successes = []
        lock = threading.Lock()

        def try_claim():
            r = sp.claim("concurrent-topic")
            with lock:
                successes.append(r)

        threads = [threading.Thread(target=try_claim) for _ in range(20)]
        for t in threads: t.start()
        for t in threads: t.join()
        assert successes.count(True) == 1
        assert successes.count(False) == 19

    def test_web_read_dedup_first_fetch(self, mod):
        sp = mod.Scratchpad()
        content = mod.web_read_dedup("https://example.com/fa3", sp)
        assert "FlashAttention" in content
        assert "[cached]" not in content
        assert sp.is_fetched("https://example.com/fa3")

    def test_web_read_dedup_cache_hit(self, mod):
        sp = mod.Scratchpad()
        mod.web_read_dedup("https://example.com/fa3", sp)
        content2 = mod.web_read_dedup("https://example.com/fa3", sp)
        assert "[cached]" in content2

    def test_multiple_findings_multiple_topics(self, mod):
        sp = mod.Scratchpad()
        sp.add_finding("FA", "claim1", "src1")
        sp.add_finding("FA", "claim2", "src2")
        sp.add_finding("PA", "claim3", "src3")
        snap = sp.snapshot_for_writer()
        assert len(snap["key_findings"]["FA"]) == 2
        assert len(snap["key_findings"]["PA"]) == 1


# ── 第六章：错误传播、重试与可观测性 ─────────────────────────────────────────

class TestCh06TraceLogger:
    @pytest.fixture(scope="class")
    def mod(self):
        return load_module("06-failure-trace",
                           "multi-agent-06-failure-trace.py")

    def test_log_and_flush(self, mod, tmp_path):
        logger = mod.TraceLogger(tmp_path / "trace.jsonl")
        logger.log("test_event", key="val", num=42)
        logger.flush()
        lines = (tmp_path / "trace.jsonl").read_text().splitlines()
        assert len(lines) == 1
        e = json.loads(lines[0])
        assert e["event"] == "test_event"
        assert e["key"] == "val"
        assert e["num"] == 42
        assert "ts" in e

    def test_multiple_events(self, mod, tmp_path):
        logger = mod.TraceLogger(tmp_path / "trace.jsonl")
        for i in range(5):
            logger.log(f"event_{i}", idx=i)
        logger.flush()
        lines = (tmp_path / "trace.jsonl").read_text().splitlines()
        assert len(lines) == 5

    def test_thread_safe_logging(self, mod, tmp_path):
        logger = mod.TraceLogger(tmp_path / "trace.jsonl")
        threads = [threading.Thread(target=lambda i=i: logger.log("evt", n=i))
                   for i in range(50)]
        for t in threads: t.start()
        for t in threads: t.join()
        logger.flush()
        lines = (tmp_path / "trace.jsonl").read_text().splitlines()
        assert len(lines) == 50


class TestCh06Retry:
    @pytest.fixture(scope="class")
    def mod(self):
        return load_module("06-failure-trace",
                           "multi-agent-06-failure-trace.py")

    def test_success_first_try(self, mod):
        calls = [0]

        @mod.with_retry(max_attempts=3, backoff=0)
        def fn():
            calls[0] += 1
            return "ok"

        assert fn() == "ok"
        assert calls[0] == 1

    def test_eventual_success(self, mod):
        calls = [0]

        @mod.with_retry(max_attempts=3, backoff=0)
        def fn():
            calls[0] += 1
            if calls[0] < 3:
                raise ValueError("not yet")
            return "done"

        assert fn() == "done"
        assert calls[0] == 3

    def test_exhausted_raises_last_exception(self, mod):
        @mod.with_retry(max_attempts=3, backoff=0)
        def fn():
            raise RuntimeError("always fails")

        with pytest.raises(RuntimeError, match="always fails"):
            fn()

    def test_selective_exception_type(self, mod):
        """on=(ValueError,) 时只对 ValueError 重试，其他异常直接抛出。"""
        calls = [0]

        @mod.with_retry(max_attempts=3, backoff=0, on=(ValueError,))
        def fn():
            calls[0] += 1
            raise TypeError("not retried")

        with pytest.raises(TypeError):
            fn()
        assert calls[0] == 1  # 没有重试

    def test_retry_logs_to_trace(self, mod, tmp_path):
        logger = mod.TraceLogger(tmp_path / "t.jsonl")
        original = mod.trace
        mod.trace = logger
        try:
            calls = [0]

            @mod.with_retry(max_attempts=3, backoff=0)
            def fn():
                calls[0] += 1
                if calls[0] < 3:
                    raise ValueError("retry me")
                return "ok"

            fn()
            logger.flush()
            lines = (tmp_path / "t.jsonl").read_text().splitlines()
            events = [json.loads(l) for l in lines]
            retry_events = [e for e in events if e["event"] == "retry"]
            assert len(retry_events) == 2
        finally:
            mod.trace = original


class TestCh06ParallelMap:
    @pytest.fixture(scope="class")
    def mod(self):
        return load_module("06-failure-trace",
                           "multi-agent-06-failure-trace.py")

    def test_all_success(self, mod):
        results, errors = mod.parallel_map_with_isolation(lambda x: x * 2, [1, 2, 3, 4, 5])
        assert results == {1: 2, 2: 4, 3: 6, 4: 8, 5: 10}
        assert errors == {}

    def test_partial_failure_isolated(self, mod):
        """一个任务失败不影响其他任务的结果。"""
        def risky(x):
            if x == 3:
                raise ValueError("x=3 fails")
            return x * 10

        results, errors = mod.parallel_map_with_isolation(risky, [1, 2, 3, 4, 5])
        assert results[1] == 10
        assert results[2] == 20
        assert 3 not in results
        assert 3 in errors
        assert results[4] == 40
        assert results[5] == 50

    def test_all_failure(self, mod):
        results, errors = mod.parallel_map_with_isolation(
            lambda x: (_ for _ in ()).throw(RuntimeError("boom")), [1, 2]
        )
        assert results == {}
        assert len(errors) == 2

    def test_parallel_execution(self, mod):
        """5 个任务应该并行，总耗时不超过串行的 60%。"""
        def slow(x):
            time.sleep(0.1)
            return x

        t0 = time.time()
        results, errors = mod.parallel_map_with_isolation(slow, list(range(5)))
        elapsed = time.time() - t0
        assert errors == {}
        assert len(results) == 5
        assert elapsed < 0.35, f"并行耗时 {elapsed:.2f}s，疑似串行执行"


class TestCh06TracedDecorator:
    @pytest.fixture(scope="class")
    def mod(self):
        return load_module("06-failure-trace",
                           "multi-agent-06-failure-trace.py")

    def test_success_logs_start_and_end(self, mod, tmp_path):
        logger = mod.TraceLogger(tmp_path / "t.jsonl")
        original = mod.trace
        mod.trace = logger
        try:
            @mod.traced("my_agent")
            def fn():
                return "done"

            fn()
            logger.flush()
            lines = (tmp_path / "t.jsonl").read_text().splitlines()
            events = {json.loads(l)["event"] for l in lines}
            assert "agent_start" in events
            assert "agent_end" in events
            assert "agent_error" not in events
        finally:
            mod.trace = original

    def test_failure_logs_start_and_error(self, mod, tmp_path):
        logger = mod.TraceLogger(tmp_path / "t.jsonl")
        original = mod.trace
        mod.trace = logger
        try:
            @mod.traced("bad_agent")
            def fn():
                raise RuntimeError("oops")

            with pytest.raises(RuntimeError):
                fn()
            logger.flush()
            lines = (tmp_path / "t.jsonl").read_text().splitlines()
            events = {json.loads(l)["event"] for l in lines}
            assert "agent_start" in events
            assert "agent_error" in events
            assert "agent_end" not in events
        finally:
            mod.trace = original

    def test_duration_recorded(self, mod, tmp_path):
        logger = mod.TraceLogger(tmp_path / "t.jsonl")
        original = mod.trace
        mod.trace = logger
        try:
            @mod.traced("timed_agent")
            def fn():
                return "x"

            fn()
            logger.flush()
            lines = (tmp_path / "t.jsonl").read_text().splitlines()
            end_events = [json.loads(l) for l in lines if json.loads(l)["event"] == "agent_end"]
            assert len(end_events) == 1
            assert "duration" in end_events[0]
            assert isinstance(end_events[0]["duration"], float)
        finally:
            mod.trace = original


# ── 第七章：边界与反模式 ──────────────────────────────────────────────────────

class TestCh07Boundaries:
    @pytest.fixture(scope="class")
    def mod(self):
        return load_module("07-boundaries",
                           "multi-agent-07-boundaries.py")

    def test_web_search_flashattention(self, mod):
        results = json.loads(mod.web_search("FlashAttention"))
        assert results[0]["url"] == "https://example.com/fa3"

    def test_web_search_pagedattention(self, mod):
        results = json.loads(mod.web_search("PagedAttention"))
        assert results[0]["url"] == "https://example.com/pa-v2"

    def test_web_search_miss(self, mod):
        assert mod.web_search("nothing here") == "[]"

    def test_web_read_all_mock_pages(self, mod):
        for url, expected_fragment in [
            ("https://example.com/fa3", "FlashAttention"),
            ("https://example.com/pa-v2", "PagedAttention"),
            ("https://example.com/sglang", "SGLang"),
            ("https://example.com/vllm", "vLLM"),
            ("https://example.com/trtllm", "TRT-LLM"),
        ]:
            content = mod.web_read(url)
            assert expected_fragment in content, f"URL {url} 返回内容不含 '{expected_fragment}'"

    def test_web_read_unknown(self, mod):
        content = mod.web_read("https://example.com/xyz")
        assert "not found" in content

    def test_mainagent_has_required_methods(self, mod):
        agent = mod.MainAgent()
        for method in ["run", "_plan", "_draft", "_revise"]:
            assert hasattr(agent, method), f"MainAgent 缺少方法 '{method}'"

    def test_critic_subagent_returns_list_on_invalid_json(self, mod):
        """当 LLM 返回无法解析的内容时，critic_subagent 应返回空列表而不崩溃。"""
        mock_msg = MagicMock()
        mock_msg.content = "这不是 JSON"
        with patch.object(mod, "llm", return_value=mock_msg):
            result = mod.critic_subagent("some report")
            assert isinstance(result, list)


# ── 跨章节一致性检查 ──────────────────────────────────────────────────────────

class TestCrossChapter:
    """验证各章 planner 的 JSON 解析边界条件。"""

    def test_json_parse_normal(self):
        """正常输入：提取 JSON 数组。"""
        text = '思路如下：["FlashAttention", "PagedAttention", "SGLang"]'
        start, end = text.find("["), text.rfind("]")
        result = json.loads(text[start:end+1]) if start >= 0 < end else []
        assert result == ["FlashAttention", "PagedAttention", "SGLang"]

    def test_json_parse_no_bracket(self):
        """无括号时返回空列表。"""
        text = "这里没有数组"
        start, end = text.find("["), text.rfind("]")
        result = json.loads(text[start:end+1]) if start >= 0 < end else []
        assert result == []

    def test_json_parse_empty_array(self):
        """空数组 [] 应返回 []。"""
        text = "结果：[]"
        start, end = text.find("["), text.rfind("]")
        result = json.loads(text[start:end+1]) if start >= 0 < end else []
        assert result == []

    def test_json_parse_end_before_start(self):
        """'] text [' 结构：end < start，不应尝试解析。"""
        text = "] garbage ["
        start, end = text.find("["), text.rfind("]")
        # start=10, end=0 → 0 >= 0 < 0 is False → 返回 []
        # 注意：这里 start=10(>0), end=0, 条件 start>=0 < end = 10>=0 and 0<0 = False ✓
        result = json.loads(text[start:end+1]) if start >= 0 < end else []
        assert result == []

    def test_ch04_all_search_urls_match_mock_pages(self):
        """ch04 修复后：所有 MOCK_SEARCH URL 应在 MOCK_PAGES 中存在。"""
        import importlib.util
        from unittest.mock import patch
        path = BASE / "04-orchestration" / "multi-agent-04-orchestration.py"
        spec = importlib.util.spec_from_file_location("ch04", path)
        mod = importlib.util.module_from_spec(spec)
        with patch("openai.OpenAI"):
            spec.loader.exec_module(mod)
        mismatched = [
            (topic, r["url"])
            for topic, results in mod.MOCK_SEARCH.items()
            for r in results
            if r["url"] not in mod.MOCK_PAGES
        ]
        assert mismatched == [], f"仍有 URL 不匹配：{mismatched}"
