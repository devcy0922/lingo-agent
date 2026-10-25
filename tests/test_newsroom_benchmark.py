from __future__ import annotations

import json

from lingo.benchmarks.newsroom import benchmark_newsroom_fixture


def test_newsroom_fixture_benchmark_uses_mock_provider(tmp_path):
    fixture_path = tmp_path / "newsroom-mock.json"
    fixture_path.write_text(
        json.dumps(
            {
                "schemaVersion": "newsroom.mock.v1",
                "cases": [
                    {
                        "id": "mock-skincare-launch-case",
                        "category": "skincare",
                        "requestedContentType": "launch",
                        "article": {
                            "id": "mock-skincare-launch",
                            "slug": "mock-skincare-launch",
                            "desk_id": "beauty",
                            "category": "skincare",
                            "content_type": "launch",
                            "headline": "스킨케어 신제품 목업",
                            "dek": "검증된 수치 하나를 포함한 결정론적 fixture",
                            "body": [
                                {
                                    "type": "paragraph",
                                    "sentences": [{"text": "검증된 목업 사실입니다."}],
                                },
                                {
                                    "type": "keynumbers",
                                    "items": [{"label": "변화", "value": "8%", "note": "fixture"}],
                                },
                            ],
                        },
                    }
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    report = benchmark_newsroom_fixture(
        fixture_path,
        category="skincare",
        content_type="launch",
        providers=["mock"],
    )

    assert report["schemaVersion"] == "lingo.newsroom-benchmark.v1"
    assert report["status"] == "PASSED"
    assert len(report["source"]["fixture_sha256"]) == 64
    assert report["summary"]["live_runtime_success_count"] == 0
    row = report["comparison"][0]
    assert row["provider"] == "mock"
    assert row["evidence"]["mode"] == "deterministic_mock"
    assert row["cost_evidence"]["status"] == "not_reported"
    assert row["postconditions"]["article_blocks_preserved"] is True
    assert row["postconditions"]["accepted"] is True
    assert report["boundaries"]["publication"] == "not_attempted"
