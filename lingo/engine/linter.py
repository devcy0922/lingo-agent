from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Set, Tuple

from lingo.types import GlossaryTerm, PathKey

_SIMPLE_VAR = re.compile(r"\{([a-zA-Z0-9_]+)\}")
_ICU_COMPLEX = re.compile(
    r"\{([a-zA-Z0-9_]+)\s*,\s*(plural|select|selectordinal)", re.IGNORECASE
)
_HTML_TAG = re.compile(r"<([a-zA-Z0-9_-]+)[^>]*>")


def extract_vars(text: str) -> Set[str]:
    """문자열에서 단순 변수 및 ICU 복합 변수 식별자를 추출합니다."""
    return set(_SIMPLE_VAR.findall(text)) | {
        match.group(1) for match in _ICU_COMPLEX.finditer(text)
    }


def extract_html_tags(text: str) -> Set[str]:
    """문자열에서 HTML 태그명을 추출합니다."""
    return {tag.lower() for tag in _HTML_TAG.findall(text)}


def leaf_map(obj: Any, path: PathKey = ()) -> Dict[PathKey, str]:
    """JSON 문자열 leaf를 구조를 보존하는 tuple 경로로 평탄화합니다."""
    result: Dict[PathKey, str] = {}
    if isinstance(obj, dict):
        for key, value in obj.items():
            result.update(leaf_map(value, path + (str(key),)))
    elif isinstance(obj, str):
        result[path] = obj
    return result


def lint_leaf_translation(
    source_val: str,
    trans_val: str,
    terms: Optional[Dict[str, GlossaryTerm]] = None,
    prohibited_phrases: Optional[List[str]] = None,
) -> Tuple[bool, List[str]]:
    """단일 문자열 번역문에 대해 정적 린트 규칙(변수, 태그, 금지어)을 검사합니다."""
    errors: List[str] = []

    # 1. ICU 변수 일치 검사
    src_vars = extract_vars(source_val)
    trans_vars = extract_vars(trans_val)
    missing_vars = src_vars - trans_vars
    if missing_vars:
        errors.append(f"누락된 ICU 변수: {', '.join(sorted(missing_vars))}")

    # 2. HTML 태그 보존 검사
    src_tags = extract_html_tags(source_val)
    trans_tags = extract_html_tags(trans_val)
    missing_tags = src_tags - trans_tags
    if missing_tags:
        errors.append(f"누락된 HTML 태그: {', '.join(sorted(missing_tags))}")

    # 3. 용어집 금지어 검사
    if terms:
        for term_obj in terms.values():
            for forbidden in term_obj.forbidden:
                if forbidden.lower() in trans_val.lower():
                    errors.append(f"용어집 금지 표현 사용: '{forbidden}'")

    # 4. 프로필 공통 금지 구문 검사
    if prohibited_phrases:
        for phrase in prohibited_phrases:
            if phrase.lower() in trans_val.lower():
                errors.append(f"프로필 금지 구문 사용: '{phrase}'")

    return (len(errors) == 0, errors)
