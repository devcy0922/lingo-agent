from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

from lingo.adapters.article_adapter import NewsroomArticleAdapter
from lingo.mcp.tools import mcp_lint_translation
from lingo.runtimes.base import TranslationTask
from lingo.runtimes.registry import RuntimeRegistry


NEWSROOM_FIXTURE_SCHEMA = "newsroom.mock.v1"
BENCHMARK_SCHEMA = "lingo.newsroom-benchmark.v1"


def _read_fixture(path: Path) -> Tuple[Dict[str, Any], str]:
    raw = path.read_bytes()
    try:
        report = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"Newsroom fixture JSON을 읽을 수 없습니다: {path}") from exc

    if not isinstance(report, dict) or report.get("schemaVersion") != NEWSROOM_FIXTURE_SCHEMA:
        raise ValueError(
            f"지원하지 않는 Newsroom fixture입니다. schemaVersion={NEWSROOM_FIXTURE_SCHEMA} 필요"
        )
    if not isinstance(report.get("cases"), list) or not report["cases"]:
        raise ValueError("Newsroom fixture에 cases가 없습니다")
    return report, hashlib.sha256(raw).hexdigest()


def _case_value(case: Dict[str, Any], article: Dict[str, Any], *keys: str) -> Optional[str]:
    for key in keys:
        value = case.get(key)
        if isinstance(value, str) and value:
            return value
        value = article.get(key)
        if isinstance(value, str) and value:
            return value
    return None


def _select_case(
    cases: Iterable[Any],
    category: Optional[str],
    content_type: Optional[str],
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    for raw_case in cases:
        if not isinstance(raw_case, dict) or not isinstance(raw_case.get("article"), dict):
            continue
        article = raw_case["article"]
        case_category = _case_value(raw_case, article, "category")
        case_types = {
            value
            for value in (
                _case_value(raw_case, article, "requestedContentType", "contentType", "content_type"),
                raw_case.get("documentContentType"),
                article.get("content_type"),
            )
            if isinstance(value, str) and value
        }
        if category and case_category != category:
            continue
        if content_type and content_type not in case_types:
            continue
        return raw_case, article

    selector = ", ".join(
        part
        for part in (
            f"category={category}" if category else "",
            f"content_type={content_type}" if content_type else "",
        )
        if part
    )
    suffix = f" ({selector})" if selector else ""
    raise ValueError(f"Newsroom fixture에서 선택 조건에 맞는 기사를 찾지 못했습니다{suffix}")


def _block_signature(body: Any) -> Optional[List[Optional[str]]]:
    if not isinstance(body, list):
        return None
    signature: List[Optional[str]] = []
    for block in body:
        if not isinstance(block, dict):
            return None
        signature.append(block.get("type"))
    return signature


def _evaluate_result(
    article: Dict[str, Any],
    task: TranslationTask,
    result_data: Optional[Dict[str, Any]],
) -> Dict[str, Any]:
    if not result_data:
        return {
            "output_shape_valid": False,
            "article_blocks_preserved": False,
            "headline_lint_passed": False,
            "accepted": False,
        }

    payload = result_data.get("translated_payload")
    evidence = (result_data.get("qa_report") or {}).get("evidence") or {}
    original_signature = _block_signature(article.get("body"))
    output_signature = _block_signature(payload.get("body")) if isinstance(payload, dict) else None
    output_shape_valid = (
        isinstance(payload, dict)
        and isinstance(payload.get("headline"), str)
        and isinstance(payload.get("dek"), str)
        and "body" in payload
        and output_signature is not None
    )
    formatted = (
        NewsroomArticleAdapter.format_translated_article(article, payload, task.target_lang)
        if output_shape_valid
        else {}
    )
    formatted_signature = _block_signature(formatted.get("body"))
    headline_lint = (
        mcp_lint_translation(article.get("headline", ""), payload["headline"])
        if output_shape_valid
        else {"passed": False, "errors": ["translated headline is unavailable"]}
    )
    article_blocks_preserved = (
        original_signature is not None
        and output_signature == original_signature
        and formatted_signature == original_signature
    )
    fallback_used = bool(evidence.get("fallback_used"))
    accepted = (
        result_data.get("status") == "SUCCESS"
        and not fallback_used
        and output_shape_valid
        and article_blocks_preserved
        and bool(headline_lint.get("passed"))
    )
    return {
        "output_shape_valid": output_shape_valid,
        "article_blocks_preserved": article_blocks_preserved,
        "headline_lint_passed": bool(headline_lint.get("passed")),
        "formatted_lang": formatted.get("lang"),
        "formatted_parent_article_id": formatted.get("parent_article_id"),
        "accepted": accepted,
    }


def _provider_names(providers: Optional[Iterable[str]]) -> List[str]:
    names = [name.strip() for name in (providers or ["mock"]) if name and name.strip()]
    if not names:
        raise ValueError("최소 하나의 Provider를 지정해야 합니다")
    return list(dict.fromkeys(names))


def _run_provider(task: TranslationTask, provider_name: str) -> Dict[str, Any]:
    try:
        report = RuntimeRegistry.benchmark_runtimes(task, providers=[provider_name])
        row = dict(report["comparison"][0])
        result_data = report["results"].get(provider_name)
        row["evidence"] = (result_data or {}).get("qa_report", {}).get("evidence", {})
        token_usage = row.get("token_usage") or {}
        row["cost_evidence"] = {
            "status": "reported" if token_usage else "not_reported",
            "basis": "provider_token_usage",
            "token_usage": token_usage,
        }
        row["result"] = result_data
        return row
    except Exception as exc:
        return {
            "provider": provider_name,
            "status": "ERROR",
            "duration_ms": 0.0,
            "stage_durations": {},
            "retry_count": 0,
            "item_count": 0,
            "qa_score": 0.0,
            "token_usage": {},
            "error": f"{type(exc).__name__}: {exc}",
            "cost_evidence": {
                "status": "not_reported",
                "basis": "provider_token_usage",
                "token_usage": {},
            },
            "evidence": {
                "mode": "provider_dispatch",
                "live_runtime": False,
                "upstream_reachable": False,
                "fallback_used": False,
            },
            "result": None,
        }


def benchmark_newsroom_fixture(
    fixture_path: Path,
    *,
    target_lang: str = "en",
    profile_name: str = "tech_blog",
    providers: Optional[Iterable[str]] = None,
    category: Optional[str] = None,
    content_type: Optional[str] = None,
) -> Dict[str, Any]:
    """Newsroom fixture 하나를 명시적인 Runtime Provider들로 재현성 있게 실행합니다."""

    report, fixture_sha256 = _read_fixture(fixture_path)
    raw_case, article = _select_case(report["cases"], category, content_type)
    article_id = article.get("id")
    if not isinstance(article_id, str) or not article_id:
        raise ValueError("선택된 Newsroom article에 id가 없습니다")

    task = NewsroomArticleAdapter.to_task(
        article,
        target_lang=target_lang,
        profile_name=profile_name,
        task_id=f"newsroom-{article_id}-{target_lang}",
    )
    selected_providers = _provider_names(providers)
    rows: List[Dict[str, Any]] = []
    for provider_name in selected_providers:
        row = _run_provider(task, provider_name)
        result_data = row.pop("result", None)
        row["postconditions"] = _evaluate_result(article, task, result_data)
        rows.append(row)

    accepted_count = sum(1 for row in rows if row["postconditions"]["accepted"])
    live_success_count = sum(
        1
        for row in rows
        if row.get("status") == "SUCCESS" and row.get("evidence", {}).get("live_runtime") is True
    )
    return {
        "schemaVersion": BENCHMARK_SCHEMA,
        "status": "PASSED" if accepted_count == len(rows) else "FAILED",
        "source": {
            "fixture_schema": report.get("schemaVersion"),
            "fixture_sha256": fixture_sha256,
            "fixture_name": fixture_path.name,
            "case_id": raw_case.get("id") or article_id,
            "article_id": article_id,
            "category": _case_value(raw_case, article, "category"),
            "content_type": _case_value(
                raw_case, article, "requestedContentType", "contentType", "content_type"
            ),
        },
        "task": {
            "task_id": task.task_id,
            "source_lang": task.source_lang,
            "target_lang": task.target_lang,
            "content_type": task.content_type,
            "profile_name": profile_name,
        },
        "providers": selected_providers,
        "summary": {
            "provider_count": len(rows),
            "accepted_count": accepted_count,
            "live_runtime_success_count": live_success_count,
            "failed_count": len(rows) - accepted_count,
        },
        "comparison": rows,
        "boundaries": {
            "newsroom_database": "not_accessed",
            "publication": "not_attempted",
            "translation_quality": "not_established_by_mock",
            "cost": "provider_token_usage_only",
            "engine_process": "executed_only_when_explicitly_selected",
        },
    }
