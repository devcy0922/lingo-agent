from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

from lingo.engine.linter import lint_leaf_translation
from lingo.glossary import load_profile
from lingo.types import GlossaryTerm


def mcp_glossary_lookup(
    term: str,
    target_lang: str = "en",
    profile_name: str = "default",
) -> Dict[str, Any]:
    """지정된 프로필과 대상 언어에서 용어집 표준 번역 및 금지 표현을 조회합니다."""
    profile = load_profile(profile_name)
    matched_term = profile.terms.get(term)
    if matched_term:
        return {
            "term": term,
            "target_lang": target_lang,
            "translation": matched_term.translations.get(target_lang, ""),
            "forbidden": matched_term.forbidden,
            "note": matched_term.note,
            "found": True,
        }
    return {
        "term": term,
        "target_lang": target_lang,
        "translation": "",
        "forbidden": [],
        "note": "",
        "found": False,
    }


def mcp_lint_translation(
    source_text: str,
    target_text: str,
    forbidden_terms: Optional[List[str]] = None,
    prohibited_phrases: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """단일 번역문에 대해 ICU 변수 보존, HTML 태그 무결성, 금지 표현을 정적 검증합니다."""
    dummy_terms = None
    if forbidden_terms:
        dummy_terms = {
            f"term_{i}": GlossaryTerm(term=t, forbidden=[t])
            for i, t in enumerate(forbidden_terms)
        }

    passed, errors = lint_leaf_translation(
        source_text,
        target_text,
        terms=dummy_terms,
        prohibited_phrases=prohibited_phrases,
    )
    return {
        "passed": passed,
        "errors": errors,
        "error_count": len(errors),
    }


def mcp_article_blocks_transform(
    article_dict: Dict[str, Any],
    translations: Dict[str, str],
) -> Dict[str, Any]:
    """뉴스룸 기사의 ArticleBlock[] 구조(문단, 수치, 인용, 불릿)를 손상 없이 번역 텍스트로 치환합니다."""
    transformed = dict(article_dict)

    if "headline" in translations:
        transformed["headline"] = translations["headline"]
    if "dek" in translations:
        transformed["dek"] = translations["dek"]

    body = article_dict.get("body", [])
    new_body = []
    count = 0

    for idx, block in enumerate(body):
        nb = dict(block)
        b_type = block.get("type", "")
        if b_type == "paragraph":
            new_sents = []
            for s_idx, sent in enumerate(block.get("sentences", [])):
                sid = f"body_{idx}_s_{s_idx}"
                ns = dict(sent)
                if sid in translations:
                    ns["text"] = translations[sid]
                    count += 1
                new_sents.append(ns)
            nb["sentences"] = new_sents
        elif b_type == "subhead":
            sid = f"body_{idx}_subhead"
            if sid in translations:
                nb["text"] = translations[sid]
                count += 1
        elif b_type == "bullets":
            new_bullets = []
            for b_idx, bullet in enumerate(block.get("items", [])):
                sid = f"body_{idx}_bullet_{b_idx}"
                if sid in translations:
                    new_bullets.append(translations[sid])
                    count += 1
                else:
                    new_bullets.append(bullet)
            nb["items"] = new_bullets
        elif b_type == "keynumbers":
            new_items = []
            for k_idx, item in enumerate(block.get("items", [])):
                lid = f"body_{idx}_kn_{k_idx}_label"
                nid = f"body_{idx}_kn_{k_idx}_note"
                ni = dict(item)
                if lid in translations:
                    ni["label"] = translations[lid]
                    count += 1
                if nid in translations:
                    ni["note"] = translations[nid]
                    count += 1
                new_items.append(ni)
            nb["items"] = new_items
        new_body.append(nb)

    transformed["body"] = new_body
    return {
        "transformed_article": transformed,
        "transformed_segments": count,
    }


def get_mcp_tool_definitions() -> List[Dict[str, Any]]:
    """MCP 프로토콜 규격의 도구 메타데이터 목록을 반환합니다."""
    return [
        {
            "name": "lingo_glossary_lookup",
            "description": "지정된 톤앤매너 프로필에서 공식 번역 용어와 금지어를 조회합니다.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "term": {"type": "string", "description": "조회할 원문 단어/용어"},
                    "target_lang": {"type": "string", "description": "대상 언어 코드 (en, ja 등)"},
                    "profile_name": {"type": "string", "description": "프로필 이름 (기본값: default)"},
                },
                "required": ["term"],
            },
        },
        {
            "name": "lingo_lint_translation",
            "description": "ICU 변수 보존, HTML 태그 무결성, 금지 표현을 정적 검증합니다.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "source_text": {"type": "string", "description": "원문 문자열"},
                    "target_text": {"type": "string", "description": "번역된 문자열"},
                    "forbidden_terms": {"type": "array", "items": {"type": "string"}, "description": "금지 단어 목록"},
                    "prohibited_phrases": {"type": "array", "items": {"type": "string"}, "description": "금지 구문 목록"},
                },
                "required": ["source_text", "target_text"],
            },
        },
        {
            "name": "lingo_article_blocks_transform",
            "description": "뉴스룸 기사의 1열 ArticleBlock[] 구조를 유지하며 번역 텍스트를 안전하게 치환합니다.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "article_dict": {"type": "object", "description": "원문 기사 사전 객체"},
                    "translations": {"type": "object", "description": "세그먼트 ID별 번역문 매핑"},
                },
                "required": ["article_dict", "translations"],
            },
        },
    ]
