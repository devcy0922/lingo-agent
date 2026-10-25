from __future__ import annotations

import json

import httpx

from lingo.runtimes.base import TranslationTask
from lingo.runtimes.engine_process_provider import EngineProcessRuntimeProvider


class _FakeResponse:
    status_code = 200
    is_success = True

    def json(self):
        return {
            "runId": "run-1",
            "operationId": "operation-1",
            "response": json.dumps(
                {
                    "id": "article-1",
                    "headline": "[EN] Headline",
                    "dek": "[EN] Dek",
                    "body": [],
                }
            ),
            "inputTokens": 120,
            "outputTokens": 40,
            "durationMs": 321.5,
            "isError": False,
        }


class _FakeClient:
    def __init__(self, captured):
        self.captured = captured

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def post(self, url, *, headers, json):
        self.captured.update({"url": url, "headers": headers, "json": json})
        return _FakeResponse()


def test_engine_process_provider_uses_real_runs_contract(monkeypatch):
    captured = {}
    monkeypatch.setattr(httpx, "Client", lambda timeout: _FakeClient(captured))

    result = EngineProcessRuntimeProvider(
        endpoint_url="http://engine-process.test:8095",
        auth_token="test-token",
    ).execute(
        TranslationTask(
            task_id="contract-check",
            target_lang="en",
            payload={"id": "article-1", "headline": "제목", "dek": "부제", "body": []},
        )
    )

    assert result.status == "SUCCESS"
    assert result.translated_payload["headline"] == "[EN] Headline"
    assert result.metrics.token_usage == {"inputTokens": 120, "outputTokens": 40}
    assert result.metrics.total_duration_ms == 321.5
    assert captured["url"] == "http://engine-process.test:8095/v1/process/runs"
    assert captured["headers"]["Authorization"] == "Bearer test-token"
    assert captured["json"]["responseFormat"] == "json_object"
    assert captured["json"]["maxTurns"] == 1
    assert "SOURCE_ARTICLE_JSON" in captured["json"]["message"]
