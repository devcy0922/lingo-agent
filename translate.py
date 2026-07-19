#!/usr/bin/env python3
"""LingoAgent 독립 실행 i18n 번역 배포 게이트."""

from __future__ import annotations

import argparse
import json
import logging
import os
import re
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

import httpx


LLM_GATEWAY_URL = os.environ.get("LLM_GATEWAY_URL", "").rstrip("/")
LLM_API_KEY = os.environ.get("LLM_API_KEY", "")
LEGACY_MODEL = os.environ.get("LLM_MODEL", "auto")
TRANSLATION_MODEL = os.environ.get("LLM_TRANSLATION_MODEL", LEGACY_MODEL)
REVIEW_MODEL = os.environ.get("LLM_REVIEW_MODEL", LEGACY_MODEL)
LLM_TIMEOUT_SECONDS = float(os.environ.get("LLM_TIMEOUT_SECONDS", "240"))
LLM_MIN_REQUEST_INTERVAL_SECONDS = float(
    os.environ.get("LLM_MIN_REQUEST_INTERVAL_SECONDS", "0")
)
LLM_REQUEST_ATTEMPTS = 4
REVIEW_SCHEMA_ATTEMPTS = 2
MAX_ATTEMPTS = 3
QA_BATCH_SIZE = 8
QA_MIN_DIMENSION_SCORE = 4

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("LingoAgent")

PathKey = tuple[str, ...]
JsonObject = dict[str, Any]

_SIMPLE_VAR = re.compile(r"\{([a-zA-Z0-9_]+)\}")
_ICU_COMPLEX = re.compile(
    r"\{([a-zA-Z0-9_]+)\s*,\s*(plural|select|selectordinal)", re.IGNORECASE
)
_last_request_at = 0.0


def _extract_vars(text: str) -> set[str]:
    """문자열에서 단순 변수와 ICU 복합 변수 식별자를 추출합니다."""
    return set(_SIMPLE_VAR.findall(text)) | {
        match.group(1) for match in _ICU_COMPLEX.finditer(text)
    }


def _leaf_map(obj: Any, path: PathKey = ()) -> dict[PathKey, str]:
    """JSON 문자열 leaf를 구조를 잃지 않는 tuple 경로로 평탄화합니다."""
    result: dict[PathKey, str] = {}
    if isinstance(obj, dict):
        for key, value in obj.items():
            result.update(_leaf_map(value, path + (key,)))
    elif isinstance(obj, str):
        result[path] = obj
    return result


def _flatten_values(obj: Any, prefix: str = "") -> dict[str, str]:
    """기존 호출부 호환용 문자열 경로 평탄화 함수입니다."""
    result: dict[str, str] = {}
    if isinstance(obj, dict):
        for key, value in obj.items():
            full_key = f"{prefix}.{key}" if prefix else key
            result.update(_flatten_values(value, full_key))
    elif isinstance(obj, str):
        result[prefix] = obj
    return result


def _path_label(path: PathKey) -> str:
    return ".".join(path)


def _build_subset(obj: JsonObject, selected: set[PathKey]) -> JsonObject:
    """선택된 leaf만 원본과 같은 JSON 구조로 복원합니다."""

    def visit(value: Any, path: PathKey) -> Any:
        if isinstance(value, dict):
            output: JsonObject = {}
            for key, child in value.items():
                built = visit(child, path + (key,))
                if built is not None:
                    output[key] = built
            return output or None
        if isinstance(value, str) and path in selected:
            return value
        return None

    return visit(obj, ()) or {}


def _merge_from_source(
    source: JsonObject, existing: JsonObject, translated: JsonObject
) -> JsonObject:
    """원본 구조를 기준으로 신규 번역과 기존 번역을 병합합니다."""
    existing_leaves = _leaf_map(existing)
    translated_leaves = _leaf_map(translated)

    def visit(value: Any, path: PathKey) -> Any:
        if isinstance(value, dict):
            return {key: visit(child, path + (key,)) for key, child in value.items()}
        if isinstance(value, str):
            if path in translated_leaves:
                return translated_leaves[path]
            if path in existing_leaves:
                return existing_leaves[path]
            raise ValueError(f"번역 값이 없는 키: {_path_label(path)}")
        return value

    return visit(source, ())


@dataclass
class TranslationScope:
    added: set[PathKey] = field(default_factory=set)
    changed: set[PathKey] = field(default_factory=set)
    missing: set[PathKey] = field(default_factory=set)
    selected: set[PathKey] = field(default_factory=set)
    removed: set[PathKey] = field(default_factory=set)
    preserved: set[PathKey] = field(default_factory=set)

    def as_dict(self) -> dict[str, Any]:
        def labels(paths: set[PathKey]) -> list[str]:
            return sorted(_path_label(path) for path in paths)

        return {
            "added": labels(self.added),
            "changed": labels(self.changed),
            "missing": labels(self.missing),
            "selected": labels(self.selected),
            "removed": labels(self.removed),
            "preserved_count": len(self.preserved),
        }


def plan_translation(
    source: JsonObject,
    existing: JsonObject,
    base_source: JsonObject | None = None,
    sync_all: bool = False,
) -> TranslationScope:
    """원본 이력과 대상 파일을 비교해 번역 범위를 결정합니다."""
    current = _leaf_map(source)
    target = _leaf_map(existing)
    previous = _leaf_map(base_source) if base_source is not None else None

    added = set(current) - set(previous or {}) if previous is not None else set()
    changed = (
        {
            path
            for path in set(current) & set(previous or {})
            if current[path] != (previous or {})[path]
        }
        if previous is not None
        else set()
    )
    missing = set(current) - set(target)
    selected = set(current) if sync_all else added | changed | missing
    return TranslationScope(
        added=added,
        changed=changed,
        missing=missing,
        selected=selected,
        removed=set(target) - set(current),
        preserved=set(current) - selected,
    )


def lint_translation(source_content: str, target_content: str) -> tuple[bool, str]:
    """JSON 구조, 키 집합과 ICU 변수 무결성을 검사합니다."""
    try:
        source = json.loads(source_content)
        target = json.loads(target_content)
    except json.JSONDecodeError as exc:
        return False, f"JSON 파싱 에러: {exc}"

    source_flat = _leaf_map(source)
    target_flat = _leaf_map(target)
    missing_keys = set(source_flat) - set(target_flat)
    extra_keys = set(target_flat) - set(source_flat)
    if missing_keys:
        return False, f"번역본에 누락된 키: {sorted(map(_path_label, missing_keys))}"
    if extra_keys:
        return False, f"소스에 없는 추가 키: {sorted(map(_path_label, extra_keys))}"

    for path, source_value in source_flat.items():
        target_value = target_flat[path]
        missing_vars = _extract_vars(source_value) - _extract_vars(target_value)
        extra_vars = _extract_vars(target_value) - _extract_vars(source_value)
        if missing_vars:
            return False, f"키 '{_path_label(path)}': 변수 유실 → {missing_vars}"
        if extra_vars:
            return False, f"키 '{_path_label(path)}': 임의 변수 삽입 → {extra_vars}"
    return True, "Lint PASSED"


def _load_json(path: Path | None, *, required: bool = False) -> JsonObject:
    if path is None:
        return {}
    if not path.exists():
        if required:
            raise FileNotFoundError(path)
        return {}
    parsed = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(parsed, dict):
        raise ValueError(f"JSON 최상위 값은 object여야 합니다: {path}")
    return parsed


def load_glossary(path: Path | None) -> JsonObject:
    glossary = _load_json(path)
    glossary.setdefault("preserve", [])
    glossary.setdefault("entries", [])
    return glossary


def validate_glossary(
    source: JsonObject,
    target: JsonObject,
    target_lang: str,
    glossary: JsonObject,
) -> tuple[bool, str]:
    """보존 용어, 필수 번역과 금지 표현을 결정적으로 검사합니다."""
    source_flat = _leaf_map(source)
    target_flat = _leaf_map(target)
    problems: list[str] = []

    for path, source_value in source_flat.items():
        target_value = target_flat.get(path, "")
        for token in glossary.get("preserve", []):
            if token in source_value and token not in target_value:
                problems.append(f"{_path_label(path)}: 보존 용어 누락 '{token}'")

        for entry in glossary.get("entries", []):
            source_term = entry.get("source", "")
            if not source_term or source_term not in source_value:
                continue
            required_term = entry.get("targets", {}).get(target_lang)
            required_present = (
                required_term.casefold() in target_value.casefold()
                if required_term and target_lang.startswith("en")
                else required_term in target_value
                if required_term
                else True
            )
            if required_term and not required_present:
                problems.append(
                    f"{_path_label(path)}: 필수 용어 '{required_term}' 누락"
                )
            for forbidden in entry.get("forbidden", {}).get(target_lang, []):
                if forbidden.casefold() in target_value.casefold():
                    problems.append(
                        f"{_path_label(path)}: 금지 표현 '{forbidden}' 사용"
                    )

    if problems:
        return False, "; ".join(problems)
    return True, "Glossary PASSED"


def infer_ui_type(key: str) -> str:
    suffix = key.rsplit(".", 1)[-1].lower()
    return {
        "title": "heading",
        "headline": "heading",
        "cta": "button",
        "link": "link",
        "desc": "body",
        "context": "body",
        "tagline": "tagline",
        "label": "short_label",
        "eyebrow": "short_label",
        "value": "metric",
    }.get(suffix, "ui_text")


def build_context(source: JsonObject, selected: set[PathKey]) -> JsonObject:
    source_flat = _leaf_map(source)
    context: JsonObject = {}
    for path in sorted(selected):
        label = _path_label(path)
        namespace = label.rsplit(".", 1)[0] if "." in label else label
        neighbors = [
            {"key": _path_label(other), "source": value}
            for other, value in source_flat.items()
            if other != path and _path_label(other).startswith(namespace + ".")
        ][:3]
        context[label] = {"type": infer_ui_type(label), "neighbors": neighbors}
    return context


def _language_style(target_lang: str) -> str:
    if target_lang.startswith("en"):
        return (
            "Use idiomatic professional portfolio English. Avoid literal Korean syntax, "
            "unnecessary Title Case, awkward noun chains, and marketing filler."
        )
    if target_lang.startswith("ja"):
        return (
            "Use natural Japanese for a technical portfolio. Avoid Korean-style noun chains, "
            "unnecessary keigo, ambiguous フロントエンド wording, and inconsistent punctuation."
        )
    return "Use concise, idiomatic UI language for the target locale."


def _chat_completion(model: str, messages: list[dict[str, str]], max_tokens: int) -> str:
    global _last_request_at

    if not LLM_GATEWAY_URL:
        raise RuntimeError("LLM_GATEWAY_URL 미설정")
    headers = {"Content-Type": "application/json"}
    if LLM_API_KEY:
        headers["Authorization"] = f"Bearer {LLM_API_KEY}"
    payload: JsonObject = {
        "model": model,
        "messages": messages,
        "temperature": 0.1,
        "max_tokens": max_tokens,
        "tool_choice": "none",
        "reasoning_effort": "none",
        "chat_template_kwargs": {"enable_thinking": False},
    }
    for attempt in range(1, LLM_REQUEST_ATTEMPTS + 1):
        elapsed = time.monotonic() - _last_request_at
        remaining = LLM_MIN_REQUEST_INTERVAL_SECONDS - elapsed
        if _last_request_at and remaining > 0:
            logger.info("Gateway 요청 간격을 위해 %.1f초 대기", remaining)
            time.sleep(remaining)

        try:
            with httpx.Client(timeout=LLM_TIMEOUT_SECONDS) as client:
                _last_request_at = time.monotonic()
                response = client.post(
                    f"{LLM_GATEWAY_URL}/chat/completions", headers=headers, json=payload
                )
                response.raise_for_status()
                raw = response.json()["choices"][0]["message"].get("content")
                if not raw:
                    raise ValueError("LLM 응답 content가 비어 있습니다")
                content = raw.strip()
                if "```" in content:
                    content = content.split("```", 2)[1].strip()
                    if content.startswith("json"):
                        content = content[4:].strip()
                return content
        except httpx.HTTPStatusError as exc:
            status = exc.response.status_code
            retryable = status == 429 or 500 <= status < 600
            if not retryable or attempt == LLM_REQUEST_ATTEMPTS:
                raise
            retry_after = exc.response.headers.get("Retry-After")
            try:
                delay = float(retry_after) if retry_after else 10 * (2 ** (attempt - 1))
            except ValueError:
                delay = 10 * (2 ** (attempt - 1))
            delay = min(max(delay, 1), 60)
            logger.warning(
                "Gateway HTTP %d — %.1f초 후 재시도 (%d/%d)",
                status,
                delay,
                attempt + 1,
                LLM_REQUEST_ATTEMPTS,
            )
            time.sleep(delay)

    raise RuntimeError("LLM 요청 재시도 한도를 초과했습니다")


def translate_with_llm(
    source_content: str,
    target_lang: str,
    feedback_history: list[str] | None = None,
    *,
    context: JsonObject | None = None,
    glossary: JsonObject | None = None,
) -> tuple[str, bool]:
    """선택된 키를 번역하며 LLM 장애는 커밋 불가 상태로 반환합니다."""
    prompt = (
        f"Translate this Korean UI locale subset into {target_lang}.\n"
        f"STYLE: {_language_style(target_lang)}\n"
        "Keep the exact JSON structure and keys. Preserve ICU variables exactly. "
        "Return only valid JSON.\n"
        f"CONTEXT: {json.dumps(context or {}, ensure_ascii=False)}\n"
        f"GLOSSARY: {json.dumps(glossary or {}, ensure_ascii=False)}\n"
        f"SOURCE: {source_content}"
    )
    if feedback_history:
        prompt += "\nFIX THESE REVIEW ISSUES:\n" + "\n".join(feedback_history)
    try:
        content = _chat_completion(
            TRANSLATION_MODEL,
            [
                {
                    "role": "system",
                    "content": "You are a professional software localization translator.",
                },
                {"role": "user", "content": prompt},
            ],
            8192,
        )
        return content, False
    except Exception as exc:
        logger.error("번역 LLM 호출 실패: %s", exc)
        return source_content, True


@dataclass
class QualityReview:
    status: str
    score: int
    critique: str
    results: list[JsonObject] = field(default_factory=list)


def _chunks(items: list[PathKey], size: int) -> Iterable[list[PathKey]]:
    for index in range(0, len(items), size):
        yield items[index : index + size]


def evaluate_quality(
    source_content: str,
    translated_content: str,
    target_lang: str,
    *,
    context: JsonObject | None = None,
    glossary: JsonObject | None = None,
) -> QualityReview:
    """이번 실행에서 생성한 모든 키를 batch로 나눠 검수합니다."""
    try:
        source = json.loads(source_content)
        translated = json.loads(translated_content)
        source_paths = sorted(_leaf_map(source))
        all_results: list[JsonObject] = []

        for batch_paths in _chunks(source_paths, QA_BATCH_SIZE):
            source_batch = _build_subset(source, set(batch_paths))
            target_batch = _build_subset(translated, set(batch_paths))
            expected_keys = [_path_label(path) for path in batch_paths]
            base_prompt = (
                f"Review every key in this Korean→{target_lang} UI translation batch.\n"
                f"STYLE: {_language_style(target_lang)}\n"
                f"EXPECTED_KEYS: {json.dumps(expected_keys, ensure_ascii=False)}\n"
                f"CONTEXT: {json.dumps(context or {}, ensure_ascii=False)}\n"
                f"GLOSSARY: {json.dumps(glossary or {}, ensure_ascii=False)}\n"
                f"SOURCE: {json.dumps(source_batch, ensure_ascii=False)}\n"
                f"TRANSLATION: {json.dumps(target_batch, ensure_ascii=False)}\n"
                "Return JSON only. The top-level key must be exactly results. "
                "Each result must contain key, "
                "semantic_accuracy, naturalness, terminology, ui_fit (integers 1-5), "
                "critical_errors (array), and critique. Example: "
                '{"results":[{"key":"example.key","semantic_accuracy":5,'
                '"naturalness":5,"terminology":5,"ui_fit":5,'
                '"critical_errors":[],"critique":""}]}'
            )
            indexed: dict[str, JsonObject] | None = None
            schema_error = ""
            content = ""
            for schema_attempt in range(1, REVIEW_SCHEMA_ATTEMPTS + 1):
                prompt = base_prompt
                if schema_error:
                    prompt += (
                        "\nYour previous response was invalid: "
                        f"{schema_error}. Return the exact requested schema without prose."
                    )
                content = _chat_completion(
                    REVIEW_MODEL,
                    [
                        {
                            "role": "system",
                            "content": (
                                "You are a strict native localization reviewer. "
                                "Do not omit keys, do not inflate scores, and use the exact JSON schema."
                            ),
                        },
                        {"role": "user", "content": prompt},
                    ],
                    2048,
                )
                try:
                    payload = json.loads(content)
                    results = payload.get("results")
                    if not isinstance(results, list):
                        raise ValueError("top-level results 배열이 없습니다")
                    candidate_indexed = {
                        item.get("key"): item
                        for item in results
                        if isinstance(item, dict)
                    }
                    missing = set(expected_keys) - set(candidate_indexed)
                    if missing:
                        raise ValueError(f"키 누락: {sorted(missing)}")
                    indexed = candidate_indexed
                    break
                except (json.JSONDecodeError, ValueError) as exc:
                    schema_error = str(exc)
                    logger.warning(
                        "QA 스키마 불일치 — reviewer 재시도 (%d/%d): %s",
                        schema_attempt,
                        REVIEW_SCHEMA_ATTEMPTS,
                        schema_error,
                    )

            if indexed is None:
                response_shape = content[:300].replace("\n", " ")
                raise ValueError(
                    f"QA 스키마 재시도 실패: {schema_error}; response={response_shape}"
                )
            all_results.extend(indexed[key] for key in expected_keys)

        scores: list[int] = []
        failed: list[str] = []
        for item in all_results:
            dimensions = [
                int(item.get(name, 0))
                for name in (
                    "semantic_accuracy",
                    "naturalness",
                    "terminology",
                    "ui_fit",
                )
            ]
            scores.extend(dimensions)
            critical = item.get("critical_errors") or []
            if min(dimensions) < QA_MIN_DIMENSION_SCORE or critical:
                failed.append(
                    f"{item.get('key')}: {item.get('critique', '')}; critical={critical}"
                )

        score = round(sum(scores) / len(scores) * 20) if scores else 0
        if failed:
            return QualityReview("FAILED", score, " | ".join(failed), all_results)
        return QualityReview("PASSED", score, "모든 변경 키가 품질 기준을 통과했습니다.", all_results)
    except Exception as exc:
        logger.error("QA 평가 실패: %s", exc)
        return QualityReview("UNAVAILABLE", -1, f"QA_UNAVAILABLE: {exc}")


class TranslationResult:
    def __init__(self, lang: str, scope: TranslationScope):
        self.lang = lang
        self.scope = scope
        self.content = ""
        self.is_fallback = False
        self.lint_passed = False
        self.glossary_passed = False
        self.qa_score = -1
        self.qa_status = "PENDING"
        self.qa_results: list[JsonObject] = []
        self.attempts = 0
        self.audit_trail: list[str] = []

    @property
    def success(self) -> bool:
        qa_ok = self.qa_status == "PASSED" or (
            self.qa_status == "SKIPPED" and not self.scope.selected
        )
        return (
            self.lint_passed
            and self.glossary_passed
            and not self.is_fallback
            and qa_ok
        )

    def as_report(self) -> JsonObject:
        return {
            "language": self.lang,
            "success": self.success,
            "scope": self.scope.as_dict(),
            "lint": "PASSED" if self.lint_passed else "FAILED",
            "glossary": "PASSED" if self.glossary_passed else "FAILED",
            "qa_status": self.qa_status,
            "qa_score": self.qa_score,
            "reviewed_keys": len(self.qa_results),
            "attempts": self.attempts,
            "audit_trail": self.audit_trail,
            "qa_results": self.qa_results,
        }


def run_pipeline(
    source_content: str,
    target_lang: str,
    *,
    existing_content: str = "{}",
    base_source_content: str | None = None,
    glossary: JsonObject | None = None,
    sync_all: bool = False,
) -> TranslationResult:
    source = json.loads(source_content)
    existing = json.loads(existing_content)
    base_source = json.loads(base_source_content) if base_source_content else None
    scope = plan_translation(source, existing, base_source, sync_all)
    result = TranslationResult(target_lang, scope)
    glossary = glossary or {"preserve": [], "entries": []}

    if not scope.selected:
        merged = _merge_from_source(source, existing, {})
        result.content = json.dumps(merged, ensure_ascii=False, indent=2)
        result.lint_passed, lint_message = lint_translation(
            source_content, result.content
        )
        result.glossary_passed = True
        result.qa_status = "SKIPPED"
        result.audit_trail.append(f"변경 키 없음 — 기존 번역 보존; {lint_message}")
        return result

    source_subset = _build_subset(source, scope.selected)
    source_subset_content = json.dumps(source_subset, ensure_ascii=False)
    context = build_context(source, scope.selected)
    feedback: list[str] = []

    for attempt in range(1, MAX_ATTEMPTS + 1):
        result.attempts = attempt
        translated_content, is_fallback = translate_with_llm(
            source_subset_content,
            target_lang,
            feedback,
            context=context,
            glossary=glossary,
        )
        result.is_fallback = is_fallback
        if is_fallback:
            result.audit_trail.append("번역 LLM 장애 — 커밋 차단")
            break

        lint_ok, lint_message = lint_translation(
            source_subset_content, translated_content
        )
        result.lint_passed = lint_ok
        result.audit_trail.append(
            f"Attempt {attempt} / Lint: {'PASSED' if lint_ok else 'FAILED'} — {lint_message}"
        )
        if not lint_ok:
            feedback.append(lint_message)
            continue

        translated = json.loads(translated_content)
        glossary_ok, glossary_message = validate_glossary(
            source_subset, translated, target_lang, glossary
        )
        result.glossary_passed = glossary_ok
        result.audit_trail.append(
            f"Attempt {attempt} / Glossary: {'PASSED' if glossary_ok else 'FAILED'} — {glossary_message}"
        )
        if not glossary_ok:
            feedback.append(glossary_message)
            continue

        review = evaluate_quality(
            source_subset_content,
            translated_content,
            target_lang,
            context=context,
            glossary=glossary,
        )
        result.qa_status = review.status
        result.qa_score = review.score
        result.qa_results = review.results
        result.audit_trail.append(
            f"Attempt {attempt} / QA: {review.status} (score={review.score}) — {review.critique}"
        )
        if review.status == "UNAVAILABLE":
            break
        if review.status == "FAILED":
            feedback.append(review.critique)
            continue

        merged = _merge_from_source(source, existing, translated)
        result.content = json.dumps(merged, ensure_ascii=False, indent=2)
        result.lint_passed, final_lint = lint_translation(source_content, result.content)
        result.glossary_passed = glossary_ok
        result.audit_trail.append(f"최종 병합 / {final_lint}")
        if result.lint_passed:
            break

    return result


def _write_report(path: Path, results: list[TranslationResult], args: argparse.Namespace) -> None:
    report = {
        "status": "PASSED" if all(result.success for result in results) else "FAILED",
        "source": str(args.source),
        "base_source": str(args.base_source) if args.base_source else None,
        "sync_all": args.sync_all,
        "translation_model": TRANSLATION_MODEL,
        "review_model": REVIEW_MODEL,
        "languages": [result.as_report() for result in results],
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description="LingoAgent 변경 키 번역 배포 게이트")
    parser.add_argument("--source", required=True, type=Path)
    parser.add_argument("--base-source", type=Path)
    parser.add_argument("--langs", nargs="+", default=["en-US", "ja-JP"])
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--glossary", type=Path)
    parser.add_argument("--report", type=Path, default=Path("lingo-report.json"))
    parser.add_argument("--sync-all", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    try:
        source = _load_json(args.source, required=True)
        base_source = _load_json(args.base_source) if args.base_source else None
        glossary = load_glossary(args.glossary)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        logger.error("입력 파일 읽기 실패: %s", exc)
        sys.exit(3)

    source_content = json.dumps(source, ensure_ascii=False)
    base_content = (
        json.dumps(base_source, ensure_ascii=False) if base_source is not None else None
    )
    results: list[TranslationResult] = []

    for lang in args.langs:
        lang_code = lang.split("-")[0]
        output_path = args.output / f"{lang_code}.json"
        try:
            existing = _load_json(output_path)
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            logger.error("기존 번역 파일 읽기 실패 (%s): %s", output_path, exc)
            sys.exit(3)

        result = run_pipeline(
            source_content,
            lang,
            existing_content=json.dumps(existing, ensure_ascii=False),
            base_source_content=base_content,
            glossary=glossary,
            sync_all=args.sync_all,
        )
        results.append(result)
        logger.info(
            "[%s] selected=%d preserved=%d QA=%s score=%d success=%s",
            lang,
            len(result.scope.selected),
            len(result.scope.preserved),
            result.qa_status,
            result.qa_score,
            result.success,
        )

    try:
        _write_report(args.report, results, args)
    except OSError as exc:
        logger.error("QA 보고서 저장 실패: %s", exc)
        sys.exit(3)

    failed = [result.lang for result in results if not result.success]
    if failed:
        logger.error("COMMIT BLOCKED: 검증 실패 언어=%s", failed)
        sys.exit(1 if any(result.is_fallback for result in results) else 2)

    if not args.dry_run:
        args.output.mkdir(parents=True, exist_ok=True)
        for result in results:
            output_path = args.output / f"{result.lang.split('-')[0]}.json"
            output_path.write_text(result.content + "\n", encoding="utf-8")
            logger.info("저장 완료: %s", output_path)

    logger.info("모든 번역 검증 완료 — 커밋 준비됨")


if __name__ == "__main__":
    main()
