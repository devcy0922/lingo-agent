from __future__ import annotations

import json
from unittest.mock import MagicMock
import pytest

from lingo.runtimes.base import RuntimeEvent, TranslationTask
from lingo.runtimes.engine_process_provider import EngineProcessRuntimeProvider
from lingo.runtimes.langgraph.nodes import TranslationNodeContext
from lingo.runtimes.langgraph_provider import LangGraphRuntimeProvider
from lingo.runtimes.mock_provider import MockRuntimeProvider
from lingo.runtimes.registry import RuntimeRegistry


@pytest.fixture
def sample_task():
    return TranslationTask(
        task_id="bench_task_01",
        source_lang="ko",
        target_lang="en",
        content_type="article_blocks",
        payload={
            "headline": "K-뷰티 스킨케어 혁신",
            "dek": "자연 유래 성분과 기능성 원료 결합",
        },
    )


def test_mock_runtime_provider(sample_task):
    provider = MockRuntimeProvider(force_qa_score=4.8)
    events = []

    result = provider.execute(sample_task, observer=events.append)

    assert result.is_success
    assert result.provider == "mock"
    assert result.metrics.qa_score == 4.8
    assert len(events) >= 3
    assert result.translated_payload["headline"] == "[EN] K-뷰티 스킨케어 혁신"


def test_engine_process_runtime_fallback(sample_task):
    provider = EngineProcessRuntimeProvider(endpoint_url="http://127.0.0.1:9999")
    result = provider.execute(sample_task)

    assert result.is_success
    assert result.provider == "engine-process"
    assert result.metrics.total_duration_ms > 0
    assert "[EN]" in result.translated_payload["headline"]


def test_langgraph_runtime_provider(sample_task):
    mock_client = MagicMock()
    mock_client.chat_completion.return_value = json.dumps({
        "translations": [
            {"id": "headline", "text": "K-Beauty Skincare Innovation"},
            {"id": "dek", "text": "Combining natural ingredients with functional actives"},
        ]
    })
    mock_judge = MagicMock()
    mock_res = MagicMock()
    mock_res.key_results = {
        "headline": MagicMock(scores={"accuracy": 5}, critiques={}, passed=True, critical_error=False),
        "dek": MagicMock(scores={"accuracy": 5}, critiques={}, passed=True, critical_error=False),
    }
    mock_judge.evaluate_batch.return_value = mock_res
    ctx = TranslationNodeContext(client=mock_client, judge=mock_judge)

    provider = LangGraphRuntimeProvider(context=ctx)
    events: list[RuntimeEvent] = []
    result = provider.execute(sample_task, observer=events.append)

    assert result.is_success
    assert result.provider == "langgraph"
    assert result.metrics.item_count == 2
    assert result.translated_payload["headline"] == "K-Beauty Skincare Innovation"
    assert len(events) >= 4


def test_runtime_registry_switching(sample_task):
    # 등록 및 전환
    RuntimeRegistry.register_instance("mock_custom", MockRuntimeProvider(force_qa_score=5.0))

    p = RuntimeRegistry.get_provider("mock_custom")
    assert p.name == "mock"

    res = p.execute(sample_task)
    assert res.metrics.qa_score == 5.0


def test_runtime_benchmark_comparison(sample_task):
    """동일한 task에 대해 복수의 런타임을 나란히 실행하고 성능과 품질을 비교하는 벤치마크 검증."""
    RuntimeRegistry.register_instance("mock_a", MockRuntimeProvider(force_qa_score=4.2))
    RuntimeRegistry.register_instance("mock_b", MockRuntimeProvider(force_qa_score=4.9))

    report = RuntimeRegistry.benchmark_runtimes(sample_task, providers=["mock_a", "mock_b"])

    assert report["task_id"] == "bench_task_01"
    assert len(report["comparison"]) == 2
    assert report["comparison"][0]["provider"] == "mock_a"
    assert report["comparison"][0]["qa_score"] == 4.2
    assert report["comparison"][1]["provider"] == "mock_b"
    assert report["comparison"][1]["qa_score"] == 4.9


def test_registry_default_is_environment_aware(monkeypatch):
    """명시된 Provider 설정이 기본 선택보다 우선한다."""
    monkeypatch.setenv("LINGO_RUNTIME_PROVIDER", "mock")
    provider = RuntimeRegistry.get_provider()
    assert provider.name == "mock"


def test_registry_benchmark_does_not_assume_two_runtimes(monkeypatch, sample_task):
    """Provider 목록을 생략해도 LangGraph와 engine-process 동시 설치를 요구하지 않는다."""
    monkeypatch.setenv("LINGO_RUNTIME_PROVIDER", "mock")
    report = RuntimeRegistry.benchmark_runtimes(sample_task)
    assert [row["provider"] for row in report["comparison"]] == ["mock"]
