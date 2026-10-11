from __future__ import annotations

import json
from unittest.mock import MagicMock
import pytest

from lingo.runtimes.base import TranslationTask
from lingo.runtimes.langgraph.graph import build_translation_graph
from lingo.runtimes.langgraph.nodes import TranslationNodeContext
from lingo.runtimes.langgraph.state import LangGraphState


@pytest.fixture
def mock_context():
    client = MagicMock()
    # 첫 번역 응답 모의
    client.chat_completion.return_value = json.dumps({
        "translations": [
            {"id": "headline", "text": "Korean Economy Grows 2.5%"},
            {"id": "body_0_s_0", "text": "Exports recovered steadily."},
        ]
    })
    judge = MagicMock()
    # QA 결과 모의
    judge_res = MagicMock()
    judge_res.key_results = {
        "headline": MagicMock(scores={"accuracy": 5}, critiques={"note": "good"}, passed=True, critical_error=False),
        "body_0_s_0": MagicMock(scores={"accuracy": 5}, critiques={"note": "good"}, passed=True, critical_error=False),
    }
    judge.evaluate_batch.return_value = judge_res

    return TranslationNodeContext(client=client, judge=judge)


def test_langgraph_full_pipeline_success(mock_context):
    graph = build_translation_graph(mock_context)

    sample_article = {
        "headline": "한국 경제 2.5% 성장",
        "body": [
            {
                "type": "paragraph",
                "sentences": [{"text": "수출이 완만히 회복되었다."}],
            }
        ],
    }

    initial_state: LangGraphState = {
        "task_id": "test_task_1",
        "source_lang": "ko",
        "target_lang": "en",
        "content_type": "article_blocks",
        "raw_payload": sample_article,
        "max_retries": 2,
        "retry_count": 0,
        "items": [],
        "events": [],
    }

    config = {"configurable": {"thread_id": "test_task_1"}}
    final_output = graph.invoke(initial_state, config=config)

    assert final_output["overall_status"] == "SUCCESS"
    assert final_output["current_stage"] == "assemble"
    assert final_output["output_payload"]["headline"] == "Korean Economy Grows 2.5%"
    assert final_output["output_payload"]["body"][0]["sentences"][0]["text"] == "Exports recovered steadily."
    assert len(final_output["events"]) >= 5


def test_langgraph_loop_retry_on_failure(mock_context):
    """린트 실패 시 루프백되어 재번역되는 동작 검증."""
    call_count = 0

    def mock_chat(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            # 첫 번째 번역에는 금지 표현이나 오류 포함 (ICU 누락)
            return json.dumps({
                "translations": [
                    {"id": "headline", "text": "Wrong translation without var"},
                ]
            })
        else:
            # 두 번째 재시도 시 올바른 번역 제공
            return json.dumps({
                "translations": [
                    {"id": "headline", "text": "Correct translation with {rate}% growth"},
                ]
            })

    mock_context.client.chat_completion.side_effect = mock_chat

    graph = build_translation_graph(mock_context)

    sample_payload = {"headline": "성장률 {rate}% 달성"}
    initial_state: LangGraphState = {
        "task_id": "test_retry_task",
        "source_lang": "ko",
        "target_lang": "en",
        "content_type": "article_blocks",
        "raw_payload": sample_payload,
        "max_retries": 2,
        "retry_count": 0,
        "items": [],
        "events": [],
    }

    config = {"configurable": {"thread_id": "test_retry_task"}}
    final_output = graph.invoke(initial_state, config=config)

    # 1회 실패 후 재시도되어 호출 횟수가 2회 이상이어야 함
    assert call_count >= 2
    assert final_output["retry_count"] >= 1
    assert "{rate}%" in final_output["output_payload"]["headline"]
