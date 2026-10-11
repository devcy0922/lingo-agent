from __future__ import annotations

from lingo.adapters.article_adapter import NewsroomArticleAdapter


def test_article_adapter_roundtrip():
    article_data = {
        "id": "art_12345",
        "desk_id": "economy",
        "slug": "bok-rate-freeze-2026",
        "headline": "한국은행, 기준금리 동결 결정",
        "dek": "물가 안정과 금융 안정 고려",
        "body": [
            {
                "type": "paragraph",
                "sentences": [{"text": "금융통화위원회는 오늘 기준금리를 연 3.50%로 유지하기로 했다."}],
            }
        ],
        "tags": ["desk:economy", "category:rate"],
    }

    # 1. to_task 변환 검증
    task = NewsroomArticleAdapter.to_task(article_data, target_lang="en")
    assert task.source_lang == "ko"
    assert task.target_lang == "en"
    assert task.content_type == "article_blocks"
    assert task.metadata["article_id"] == "art_12345"
    assert task.metadata["desk_id"] == "economy"

    # 2. format_translated_article 검증
    translated_payload = {
        "headline": "Bank of Korea Freezes Benchmark Interest Rate",
        "dek": "Weighing price stability and financial markets",
        "body": [
            {
                "type": "paragraph",
                "sentences": [{"text": "The Monetary Policy Board decided today to maintain the policy rate at 3.50%."}],
            }
        ],
    }

    formatted = NewsroomArticleAdapter.format_translated_article(article_data, translated_payload, "en")
    assert formatted["lang"] == "en"
    assert formatted["parent_article_id"] == "art_12345"
    assert formatted["slug"] == "en-bok-rate-freeze-2026"
    assert formatted["headline"] == "Bank of Korea Freezes Benchmark Interest Rate"
    assert "lang:en" in formatted["tags"]
    assert formatted["body"][0]["sentences"][0]["text"] == "The Monetary Policy Board decided today to maintain the policy rate at 3.50%."
