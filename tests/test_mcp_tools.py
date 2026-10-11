from __future__ import annotations

from lingo.mcp.tools import (
    get_mcp_tool_definitions,
    mcp_article_blocks_transform,
    mcp_glossary_lookup,
    mcp_lint_translation,
)


def test_mcp_glossary_lookup():
    res = mcp_glossary_lookup("알 수 없는 단어", target_lang="en", profile_name="default")
    assert isinstance(res, dict)
    assert res["term"] == "알 수 없는 단어"
    assert "found" in res


def test_mcp_lint_translation():
    # 1. 정상 통과
    res_ok = mcp_lint_translation("환영합니다 {name}님", "Welcome {name}!")
    assert res_ok["passed"] is True
    assert res_ok["error_count"] == 0

    # 2. ICU 변수 누락 실패
    res_err = mcp_lint_translation("환영합니다 {name}님", "Welcome!")
    assert res_err["passed"] is False
    assert any("누락된 ICU 변수" in e for e in res_err["errors"])

    # 3. 금지어 검출
    res_forbid = mcp_lint_translation("테스트", "Bad translation with forbidden", forbidden_terms=["forbidden"])
    assert res_forbid["passed"] is False
    assert any("금지 표현" in e for e in res_forbid["errors"])


def test_mcp_article_blocks_transform():
    article = {
        "headline": "원문 제목",
        "dek": "원문 부제",
        "body": [
            {
                "type": "paragraph",
                "sentences": [{"text": "원문 문장 1"}, {"text": "원문 문장 2"}],
            },
            {
                "type": "keynumbers",
                "items": [{"label": "성장률", "value": "3.5%", "note": "전년 대비"}],
            },
        ],
    }

    translations = {
        "headline": "Translated Headline",
        "dek": "Translated Dek",
        "body_0_s_0": "Translated Sentence 1",
        "body_0_s_1": "Translated Sentence 2",
        "body_1_kn_0_label": "Growth Rate",
        "body_1_kn_0_note": "Year over Year",
    }

    res = mcp_article_blocks_transform(article, translations)
    out = res["transformed_article"]

    assert out["headline"] == "Translated Headline"
    assert out["dek"] == "Translated Dek"
    assert out["body"][0]["sentences"][0]["text"] == "Translated Sentence 1"
    assert out["body"][0]["sentences"][1]["text"] == "Translated Sentence 2"
    assert out["body"][1]["items"][0]["label"] == "Growth Rate"
    assert out["body"][1]["items"][0]["note"] == "Year over Year"
    assert res["transformed_segments"] == 4


def test_get_mcp_tool_definitions():
    defs = get_mcp_tool_definitions()
    assert len(defs) >= 3
    tool_names = [d["name"] for d in defs]
    assert "lingo_glossary_lookup" in tool_names
    assert "lingo_lint_translation" in tool_names
    assert "lingo_article_blocks_transform" in tool_names
