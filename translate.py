#!/usr/bin/env python3
"""
LingoAgent 독립 실행 번역 CLI
=================================
FastAPI / SQLAlchemy 없이 단독으로 실행 가능한 번역 파이프라인입니다.
GitHub Action 또는 로컬 스크립트로 직접 호출합니다.

사용법:
    python translate.py \
        --source docs/public/locales/ko.json \
        --langs en-US ja-JP \
        --output docs/public/locales/ \
        [--dry-run]

환경변수:
    LLM_GATEWAY_URL   — LLM 게이트웨이 주소 (필수)
    LLM_API_KEY       — API 키 (Optional, 게이트웨이가 요구하는 경우)
    LLM_MODEL         — 모델명 (기본값: auto)

종료 코드:
    0  — 모든 번역 완료 (lint + QA 통과)
    1  — LLM 장애로 Fallback 번역 발생 → 커밋 차단
    2  — 린트 또는 QA 검증 3회 모두 실패
    3  — 입력/출력 파일 I/O 오류
"""

import argparse
import json
import logging
import os
import re
import sys
from pathlib import Path

import httpx

# ──────────────────────────────────────────
# 설정
# ──────────────────────────────────────────
LLM_GATEWAY_URL = os.environ.get("LLM_GATEWAY_URL", "").rstrip("/")
LLM_API_KEY     = os.environ.get("LLM_API_KEY", "")
LLM_MODEL       = os.environ.get("LLM_MODEL", "auto")
QA_PASS_SCORE   = 85   # QA 합격 점수 컷오프
MAX_ATTEMPTS    = 3    # 최대 재시도 횟수

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S"
)
logger = logging.getLogger("LingoAgent")


# ──────────────────────────────────────────
# ICU 변수 추출 (중첩 JSON + plural/select 포함)
# ──────────────────────────────────────────
# 단순 변수: {count}, {username}
_SIMPLE_VAR = re.compile(r"\{([a-zA-Z0-9_]+)\}")
# ICU plural/select 패턴 (첫 식별자만 캡처): {count, plural, ...}
_ICU_COMPLEX = re.compile(r"\{([a-zA-Z0-9_]+)\s*,\s*(plural|select|selectordinal)", re.IGNORECASE)


def _extract_vars(text: str) -> set[str]:
    """텍스트에서 ICU 변수 식별자를 추출합니다 (simple + plural/select 포함)."""
    simple = set(_SIMPLE_VAR.findall(text))
    # plural/select의 중간 키워드(plural, select)는 제거하고 식별자만 유지
    complex_ids = {m.group(1) for m in _ICU_COMPLEX.finditer(text)}
    return simple | complex_ids


def _flatten_values(obj, prefix="") -> dict[str, str]:
    """중첩 JSON의 모든 문자열 값을 평탄화합니다."""
    result = {}
    if isinstance(obj, dict):
        for k, v in obj.items():
            full_key = f"{prefix}.{k}" if prefix else k
            result.update(_flatten_values(v, full_key))
    elif isinstance(obj, str):
        result[prefix] = obj
    return result


# ──────────────────────────────────────────
# 정적 린터 (ICU 변수 무결성 검사)
# ──────────────────────────────────────────

def lint_translation(source_content: str, target_content: str) -> tuple[bool, str]:
    """
    번역 결과 JSON의 무결성을 검사합니다.

    검사 항목:
    1. JSON 파싱 가능 여부
    2. 키 목록 일치 여부 (누락 / 추가 키 감지)
    3. ICU 변수 집합 보존 여부 (simple + plural/select)
    """
    try:
        src = json.loads(source_content)
        tgt = json.loads(target_content)
    except json.JSONDecodeError as e:
        return False, f"JSON 파싱 에러: {e}"

    src_flat = _flatten_values(src)
    tgt_flat = _flatten_values(tgt)

    missing_keys = set(src_flat.keys()) - set(tgt_flat.keys())
    extra_keys   = set(tgt_flat.keys()) - set(src_flat.keys())

    if missing_keys:
        return False, f"번역본에 누락된 키: {sorted(missing_keys)}"
    if extra_keys:
        return False, f"소스에 없는 추가 키: {sorted(extra_keys)}"

    for key, src_val in src_flat.items():
        tgt_val = tgt_flat.get(key, "")
        src_vars = _extract_vars(src_val)
        tgt_vars = _extract_vars(tgt_val)

        missing_vars = src_vars - tgt_vars
        extra_vars   = tgt_vars - src_vars

        if missing_vars:
            return False, f"키 '{key}': 변수 유실 → {missing_vars}"
        if extra_vars:
            return False, f"키 '{key}': 임의 변수 삽입 → {extra_vars}"

    return True, "Lint PASSED"


# ──────────────────────────────────────────
# LLM 호출: 번역
# ──────────────────────────────────────────

def translate_with_llm(
    source_content: str,
    target_lang: str,
    feedback_history: list[str] | None = None
) -> tuple[str, bool]:
    """
    LLM 게이트웨이에 번역을 요청합니다.

    반환값:
        (translated_content, is_fallback)
        is_fallback=True 이면 LLM 장애로 로컬 규칙 번역 사용됨 → 커밋 불가
    """
    if not LLM_GATEWAY_URL:
        logger.warning("LLM_GATEWAY_URL 미설정 — Fallback 번역으로 전환")
        return _fallback_translation(source_content, target_lang), True

    prompt = (
        f"You are an expert i18n translation system. "
        f"Translate the following Korean UI locale JSON into '{target_lang}'.\n\n"
        f"CRITICAL REQUIREMENTS:\n"
        f"1. Keep the exact same JSON keys. Do NOT translate keys.\n"
        f"2. Maintain ICU Message variables (e.g. {{count}}, {{username}}) exactly as-is.\n"
        f"3. For ICU plural/select patterns, preserve the full pattern structure.\n"
        f"4. Return ONLY a valid JSON object. No markdown, no explanation.\n\n"
        f"Korean JSON:\n{source_content}\n"
    )

    if feedback_history:
        prompt += "\nFix these errors from previous attempt:\n"
        for fb in feedback_history:
            prompt += f"- {fb}\n"

    headers = {"Content-Type": "application/json"}
    if LLM_API_KEY:
        headers["Authorization"] = f"Bearer {LLM_API_KEY}"

    try:
        # GCP API Gateway 버퍼링 구조상 응답이 지연될 수 있으므로 넉넉히 설정
        with httpx.Client(timeout=90.0) as client:
            resp = client.post(
                f"{LLM_GATEWAY_URL}/chat/completions",
                headers=headers,
                json={
                    "model": LLM_MODEL,
                    "messages": [
                        {"role": "system", "content": "You are a professional software localization system. Return only valid JSON."},
                        {"role": "user",   "content": prompt},
                    ],
                    "temperature": 0.2,
                    # ko.json 56개 키 × 평균 30토큰 ≈ 1700토큰 출력 예상,
                    # 일본어/중국어는 더 길어질 수 있으므로 충분히 설정
                    "max_tokens": 8192,
                }
            )
            resp.raise_for_status()
            raw = resp.json()["choices"][0]["message"].get("content")
            if raw is None:
                # tool_calls 등으로 content가 null인 경우 → Fallback 처리
                raise ValueError("LLM 응답 content가 null입니다 (tool_call 응답이거나 모델 오류)")
            content = raw.strip()

            # Markdown 코드 블록 제거
            if "```json" in content:
                content = content.split("```json")[1].split("```")[0].strip()
            elif "```" in content:
                content = content.split("```")[1].split("```")[0].strip()

            return content, False

    except Exception as e:
        logger.error(f"LLM 호출 실패: {e} — Fallback 번역 사용")
        return _fallback_translation(source_content, target_lang), True


def _fallback_translation(source_content: str, target_lang: str) -> str:
    """
    LLM 불가 시 사용하는 로컬 규칙 번역 (표시용만 — 커밋 금지).
    is_fallback=True 로 표시되어 GitHub Action을 실패시킵니다.
    """
    try:
        data = json.loads(source_content)
        flat = _flatten_values(data)
        mock = {}
        for k, v in flat.items():
            if target_lang.startswith("en"):
                mock[k] = f"[FALLBACK-EN] {v}"
            elif target_lang.startswith("ja"):
                mock[k] = f"[FALLBACK-JA] {v}"
            else:
                mock[k] = f"[FALLBACK-{target_lang}] {v}"
        return json.dumps(mock, ensure_ascii=False, indent=2)
    except Exception:
        return source_content


# ──────────────────────────────────────────
# LLM 호출: 품질 평가 (QA Judge)
# ──────────────────────────────────────────

def evaluate_quality(
    source_content: str,
    translated_content: str,
    target_lang: str
) -> tuple[int, str]:
    """
    LLM-as-a-Judge로 번역 품질을 평가합니다.

    반환값:
        (score, critique) — score=-1이면 QA API 불가
    """
    if not LLM_GATEWAY_URL:
        return -1, "QA_UNAVAILABLE: LLM_GATEWAY_URL 미설정"

    # QA 프롬프트를 짧게 유지하기 위해 샘플 5개만 사용
    # (전체 JSON을 넣으면 프롬프트가 너무 길어 모델이 content=null로 응답)
    try:
        src_sample = json.loads(source_content)
        tgt_sample = json.loads(translated_content)
        sample_keys = list(src_sample.keys())[:5]
        src_snippet = json.dumps({k: src_sample[k] for k in sample_keys}, ensure_ascii=False)
        tgt_snippet = json.dumps({k: tgt_sample[k] for k in sample_keys if k in tgt_sample}, ensure_ascii=False)
    except Exception:
        src_snippet = source_content[:500]
        tgt_snippet = translated_content[:500]

    prompt = (
        f"Rate this Korean→{target_lang} UI translation quality (sample of 5 keys).\n"
        f"Source: {src_snippet}\n"
        f"Translation: {tgt_snippet}\n"
        f"Reply with JSON only: {{\"score\": 0-100, \"critique\": \"one sentence\"}}"
    )

    headers = {"Content-Type": "application/json"}
    if LLM_API_KEY:
        headers["Authorization"] = f"Bearer {LLM_API_KEY}"

    try:
        with httpx.Client(timeout=90.0) as client:
            resp = client.post(
                f"{LLM_GATEWAY_URL}/chat/completions",
                headers=headers,
                json={
                    "model": LLM_MODEL,
                    "messages": [
                        {"role": "system", "content": "You are a localization QA judge. Respond with JSON: {\"score\": 0-100, \"critique\": \"one sentence\"}"},
                        {"role": "user",   "content": prompt},
                    ],
                    # response_format 미사용: GCP LiteLLM 프록시 호환성 문제
                    "temperature": 0.1,
                    "max_tokens": 256,
                }
            )
            resp.raise_for_status()
            raw = resp.json()["choices"][0]["message"].get("content")
            if raw is None:
                raise ValueError("QA 응답 content가 null입니다")
            content = raw.strip()
            # Markdown 블록 제거 후 JSON 파싱
            if "```" in content:
                content = content.split("```")[1].split("```")[0].strip()
                if content.startswith("json"):
                    content = content[4:].strip()
            qa_data = json.loads(content)
            return int(qa_data.get("score", 0)), qa_data.get("critique", "")

    except Exception as e:
        logger.error(f"QA 평가 실패: {e}")
        return -1, f"QA_UNAVAILABLE: {e}"


# ──────────────────────────────────────────
# 단일 언어 번역 파이프라인
# ──────────────────────────────────────────

class TranslationResult:
    def __init__(self, lang: str):
        self.lang         = lang
        self.content      = ""
        self.is_fallback  = False
        self.lint_passed  = False
        self.qa_score     = -1
        self.qa_status    = "PENDING"   # PASSED / FAILED / UNAVAILABLE
        self.attempts     = 0
        self.audit_trail  = []          # 검증 과정 기록

    @property
    def success(self) -> bool:
        return (
            self.lint_passed
            and not self.is_fallback
            and self.qa_status == "PASSED"
        )


def run_pipeline(source_content: str, target_lang: str) -> TranslationResult:
    """
    단일 언어에 대한 번역 + 린트 + QA 파이프라인을 실행합니다.
    최대 MAX_ATTEMPTS회 재시도합니다.
    """
    result = TranslationResult(target_lang)
    feedback_list: list[str] = []

    for attempt in range(1, MAX_ATTEMPTS + 1):
        result.attempts = attempt
        logger.info(f"[{target_lang}] 번역 시도 {attempt}/{MAX_ATTEMPTS}")

        # 1. 번역
        translated, is_fallback = translate_with_llm(source_content, target_lang, feedback_list)
        result.content     = translated
        result.is_fallback = is_fallback

        if is_fallback:
            msg = f"Attempt {attempt}: LLM 장애 — Fallback 번역 사용 (커밋 불가)"
            logger.warning(msg)
            result.audit_trail.append(msg)
            break  # 재시도해도 LLM이 없으면 의미 없음

        # 2. 정적 린트
        lint_ok, lint_msg = lint_translation(source_content, translated)
        result.lint_passed = lint_ok
        audit_msg = f"Attempt {attempt} / Lint: {'PASSED' if lint_ok else 'FAILED'} — {lint_msg}"
        result.audit_trail.append(audit_msg)
        logger.info(f"[{target_lang}] {audit_msg}")

        if not lint_ok:
            feedback_list.append(f"Lint Error: {lint_msg}")
            continue  # 린트 실패 시 재번역

        # 3. QA 품질 평가
        score, critique = evaluate_quality(source_content, translated, target_lang)
        result.qa_score = score

        if score == -1:
            result.qa_status = "UNAVAILABLE"
            msg = f"Attempt {attempt} / QA: UNAVAILABLE — {critique}"
            result.audit_trail.append(msg)
            logger.warning(f"[{target_lang}] {msg}")
            # QA 불가 시 파이프라인 실패 (기본 통과 점수 부여 금지)
            break

        qa_msg = f"Attempt {attempt} / QA Score: {score} — {critique}"
        result.audit_trail.append(qa_msg)
        logger.info(f"[{target_lang}] {qa_msg}")

        if score >= QA_PASS_SCORE:
            result.qa_status = "PASSED"
            logger.info(f"[{target_lang}] ✅ 검증 완료 (Score: {score})")
            break
        else:
            result.qa_status = "FAILED"
            feedback_list.append(f"QA Score {score} < {QA_PASS_SCORE}: {critique}")

    return result


# ──────────────────────────────────────────
# 메인 진입점
# ──────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="LingoAgent — ko.json → 다국어 번역 파이프라인"
    )
    parser.add_argument(
        "--source", required=True,
        help="번역 원본 ko.json 파일 경로"
    )
    parser.add_argument(
        "--langs", nargs="+", default=["en-US", "ja-JP"],
        help="번역 대상 언어 목록 (기본값: en-US ja-JP)"
    )
    parser.add_argument(
        "--output", required=True,
        help="번역 결과 JSON 파일 저장 디렉토리 경로"
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="번역 및 검증만 수행하고 파일은 저장하지 않음"
    )
    args = parser.parse_args()

    # 원본 파일 읽기
    source_path = Path(args.source)
    if not source_path.exists():
        logger.error(f"소스 파일을 찾을 수 없습니다: {source_path}")
        sys.exit(3)

    try:
        source_content = source_path.read_text(encoding="utf-8")
        json.loads(source_content)  # 유효한 JSON인지 사전 확인
    except (OSError, json.JSONDecodeError) as e:
        logger.error(f"소스 파일 읽기 실패: {e}")
        sys.exit(3)

    output_dir = Path(args.output)

    logger.info("=" * 60)
    logger.info("LingoAgent 번역 파이프라인 시작")
    logger.info(f"  소스  : {source_path}")
    logger.info(f"  언어  : {args.langs}")
    logger.info(f"  출력  : {output_dir}")
    logger.info(f"  모델  : {LLM_MODEL}")
    logger.info(f"  게이트웨이: {'설정됨' if LLM_GATEWAY_URL else '미설정 (Fallback 모드)'}")
    logger.info(f"  Dry-run : {args.dry_run}")
    logger.info("=" * 60)

    results: list[TranslationResult] = []

    for lang in args.langs:
        result = run_pipeline(source_content, lang)
        results.append(result)

        # 감사 트레일 출력
        logger.info(f"\n{'─'*40}")
        logger.info(f"[{lang}] 결과 요약:")
        logger.info(f"  is_fallback : {result.is_fallback}")
        logger.info(f"  lint_passed : {result.lint_passed}")
        logger.info(f"  qa_status   : {result.qa_status} (score={result.qa_score})")
        logger.info(f"  attempts    : {result.attempts}")
        for i, trail in enumerate(result.audit_trail, 1):
            logger.info(f"  [{i}] {trail}")
        logger.info("─" * 40)

    # ─── 성공 여부 판정 ───
    fallback_langs = [r.lang for r in results if r.is_fallback]
    qa_failed_langs = [r.lang for r in results if not r.success and not r.is_fallback]
    success_langs = [r.lang for r in results if r.success]

    logger.info("\n" + "=" * 60)
    logger.info("파이프라인 최종 결과")
    logger.info(f"  성공      : {success_langs}")
    logger.info(f"  Fallback  : {fallback_langs}")
    logger.info(f"  실패      : {qa_failed_langs}")

    # ─── Fallback이 있으면 exit(1) → GitHub Action 실패 ───
    if fallback_langs:
        logger.error(
            f"\n🚫 COMMIT BLOCKED: {fallback_langs} 언어에 Fallback 번역이 사용되었습니다.\n"
            f"   LLM Gateway 연결을 확인하고 재실행하세요."
        )
        sys.exit(1)

    if qa_failed_langs:
        logger.error(
            f"\n🚫 COMMIT BLOCKED: {qa_failed_langs} 언어가 {MAX_ATTEMPTS}회 재시도 후에도 검증 통과에 실패했습니다."
        )
        sys.exit(2)

    if not args.dry_run:
        # ─── 파일 저장 (검증 통과한 언어만) ───
        output_dir.mkdir(parents=True, exist_ok=True)
        for result in results:
            if result.success:
                # 언어 코드에서 파일명 생성: en-US → en.json
                lang_code = result.lang.split("-")[0]
                out_path = output_dir / f"{lang_code}.json"
                try:
                    parsed = json.loads(result.content)
                    out_path.write_text(
                        json.dumps(parsed, ensure_ascii=False, indent=2),
                        encoding="utf-8"
                    )
                    logger.info(f"✅ 저장 완료: {out_path}")
                except (OSError, json.JSONDecodeError) as e:
                    logger.error(f"파일 저장 실패 ({out_path}): {e}")
                    sys.exit(3)

        logger.info("\n✅ 모든 번역 완료 — 커밋 준비됨")
    else:
        logger.info("\n✅ Dry-run 완료 — 파일 저장 건너뜀")

    sys.exit(0)


if __name__ == "__main__":
    main()
