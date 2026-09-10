import json
import re
import logging
import httpx
from sqlalchemy.orm import Session
from config import settings
from models import Job, Translation

logger = logging.getLogger("LingoAgent")
logging.basicConfig(level=logging.INFO)

# ICU Message Format 변수 추출을 위한 정규식
# 예: {count}, {username} 등을 캡처
VAR_PATTERN = re.compile(r"\{([a-zA-Z0-9_]+)\}")

def extract_variables(text: str) -> set:
    """텍스트 내 중괄호 변수를 추출합니다."""
    return set(VAR_PATTERN.findall(text))


def _flatten_json(value, prefix=()):
    if isinstance(value, dict):
        for key, child in value.items():
            yield from _flatten_json(child, (*prefix, str(key)))
    else:
        yield prefix, value

def _gateway_headers() -> dict:
    if settings.LLM_API_KEY:
        return {"Authorization": f"Bearer {settings.LLM_API_KEY}"}
    return {}

def lint_translation(source_content: str, target_content: str) -> tuple[bool, str]:
    """
    번역본 JSON에 대한 정적 린팅 및 검증을 수행합니다.
    1. 올바른 JSON 구조인지 파싱 테스트
    2. 소스 Key와 타깃 Key 목록의 일치 여부
    3. 중괄호 변수(예: {username})가 유실되었거나 임의 변경되었는지 확인
    """
    try:
        source_json = json.loads(source_content)
        target_json = json.loads(target_content)
    except json.JSONDecodeError as e:
        return False, f"JSON 파싱 에러: {str(e)}"

    # 1. 중첩 JSON의 leaf key와 타입 검사
    source_values = dict(_flatten_json(source_json))
    target_values = dict(_flatten_json(target_json))
    source_keys = set(source_values)
    target_keys = set(target_values)

    missing_keys = source_keys - target_keys
    extra_keys = target_keys - source_keys

    if missing_keys:
        return False, f"번역본에 누락된 키가 존재합니다: {list(missing_keys)}"
    if extra_keys:
        return False, f"소스에 없는 잘못된 키가 포함되었습니다: {list(extra_keys)}"

    # 2. ICU 변수 무결성 검사
    for key, src_val in source_values.items():
        key_label = ".".join(key)
        tgt_val = target_values.get(key)
        if not isinstance(src_val, str):
            if type(src_val) is not type(tgt_val):
                return False, f"키 '{key_label}'의 JSON 타입이 변경되었습니다."
            continue
        if not isinstance(tgt_val, str):
            return False, f"키 '{key_label}'의 번역값이 문자열이 아닙니다."

        src_vars = extract_variables(src_val)
        tgt_vars = extract_variables(tgt_val)

        missing_vars = src_vars - tgt_vars
        extra_vars = tgt_vars - src_vars

        if missing_vars:
            return False, f"키 '{key_label}' 번역에서 변수가 유실되었습니다: {list(missing_vars)}"
        if extra_vars:
            return False, f"키 '{key_label}' 번역에 임의의 변수가 삽입되었습니다: {list(extra_vars)}"

    return True, "Passed"


async def translate_with_llm(source_content: str, target_lang: str, feedback_history: list = None) -> tuple[str, bool]:
    """
    LiteLLM / vLLM Gateway를 호출해 번역을 수행합니다.
    연결이 불가능할 경우, 시연용 mock 번역 결과물을 안정적으로 반환하여 데모의 견고함을 지킵니다.
    """
    prompt = (
        f"You are an expert i18n translation system. Translate the following Korean UI locale JSON content into '{target_lang}'.\n"
        f"CRITICAL REQUIREMENTS:\n"
        f"1. Keep the exact same JSON keys. Do NOT translate keys.\n"
        f"2. Maintain ICU Message variables inside curly braces (e.g. {{count}}, {{username}}) exactly as they are. Do not translate inside braces.\n"
        f"3. Return ONLY a valid JSON string wrapped in backticks. Do not include introductory or concluding text.\n\n"
        f"Korean JSON Input:\n"
        f"{source_content}\n"
    )

    if feedback_history:
        prompt += "\nATTENTION: Please fix the errors from the previous attempt:\n"
        for fb in feedback_history:
            prompt += f"- {fb}\n"

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            response = await client.post(
                f"{settings.LLM_GATEWAY_URL}/chat/completions",
                headers=_gateway_headers(),
                json={
                    "model": settings.LLM_MODEL,
                    "messages": [
                        {"role": "system", "content": "You are a professional software localization system."},
                        {"role": "user", "content": prompt}
                    ],
                    "temperature": 0.2
                }
            )
            if response.status_code == 200:
                result = response.json()
                content = result["choices"][0]["message"]["content"].strip()
                # Markdown JSON Block 정제
                if "```json" in content:
                    content = content.split("```json")[1].split("```")[0].strip()
                elif "```" in content:
                    content = content.split("```")[1].split("```")[0].strip()
                return content, False
            else:
                logger.warning(f"LLM Gateway returned status {response.status_code}. Using mock fallback.")
    except Exception as e:
        logger.error(f"LLM Gateway connection failed: {e}. Executing fallback translation for demo integrity.")

    # Fallback Mock Translation (데모 환경 무중단 보장)
    return simulate_fallback_translation(source_content, target_lang), True


def simulate_fallback_translation(source_content: str, target_lang: str) -> str:
    """데모를 위해 LLM API 통신 불가 시 로컬에서 간단한 번역 룰에 따라 번역 JSON을 흉내냅니다."""
    try:
        data = json.loads(source_content)
        def translate_value(v):
            if isinstance(v, dict):
                return {k: translate_value(child) for k, child in v.items()}
            if not isinstance(v, str):
                return v
            if target_lang.startswith("en"):
                # en-US Fallback
                val = f"[EN] {v}"
                # 중괄호 변수가 번역 결과물에 남도록 단순 매핑
                val = val.replace("님", "").replace("개", " units")
            elif target_lang.startswith("ja"):
                # ja-JP Fallback
                val = f"[JA] {v}"
                val = val.replace("님", "様").replace("개", "個")
            else:
                val = f"[{target_lang}] {v}"
            return val

        mock_data = translate_value(data)
        return json.dumps(mock_data, ensure_ascii=False, indent=2)
    except:
        return source_content


async def evaluate_quality_with_llm(source_content: str, translated_content: str, target_lang: str) -> tuple[int, str, str]:
    """
    LLM-as-a-Judge 품질 평가를 실행합니다.
    0-100 사이의 점수와 정성 피드백 평점을 산출합니다.
    """
    prompt = (
        f"You are a professional localization QA reviewer. Evaluate the following translation from Korean to '{target_lang}'.\n"
        f"Source (Korean):\n{source_content}\n\n"
        f"Translated JSON:\n{translated_content}\n\n"
        f"Analyze the accuracy, natural phrasing, and tone of the translation. Return your result in JSON format like this:\n"
        f"{{\n"
        f"  \"score\": 95,\n"
        f"  \"critique\": \"The translation is natural and preserves variables accurately.\"\n"
        f"}}"
    )

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            response = await client.post(
                f"{settings.LLM_GATEWAY_URL}/chat/completions",
                headers=_gateway_headers(),
                json={
                    "model": settings.LLM_MODEL,
                    "messages": [
                        {"role": "system", "content": "You are a localization QA judge. Be objective."},
                        {"role": "user", "content": prompt}
                    ],
                    "response_format": {"type": "json_object"},
                    "temperature": 0.1
                }
            )
            if response.status_code == 200:
                result = response.json()
                content = result["choices"][0]["message"]["content"].strip()
                eval_data = json.loads(content)
                return int(eval_data.get("score", 0)), eval_data.get("critique", "N/A"), "AVAILABLE"
    except Exception as e:
        logger.error(f"QA Evaluation failed: {e}.")

    # QA를 받지 못한 결과는 성공으로 간주하지 않는다.
    return -1, "QA 서비스를 사용할 수 없어 품질을 판정하지 못했습니다.", "UNAVAILABLE"


async def run_lingo_agent_loop(job_id: str, db: Session):
    """
    각 언어별 번역 및 린트 검사, LLM 품질 검증을 자율적으로 돌리는 오케스트레이터 루프입니다.
    """
    job = db.query(Job).filter(Job.id == job_id).first()
    if not job:
        logger.error(f"Job {job_id} not found.")
        return

    job.status = "TRANSLATING"
    db.commit()

    target_langs = job.target_langs
    for lang in target_langs:
        # Translation 레코드 조회 또는 생성
        trans = db.query(Translation).filter(
            Translation.job_id == job_id,
            Translation.target_lang == lang
        ).first()

        if not trans:
            trans = Translation(
                job_id=job_id,
                target_lang=lang,
                lint_status="PENDING",
                quality_score=0,
                feedback_log=[],
                attempts=0
            )
            db.add(trans)
            db.commit()

        success = False
        feedback_list = list(trans.feedback_log or [])

        while trans.attempts < 3:
            trans.attempts += 1
            db.commit()

            logger.info(f"Job {job_id} [{lang}] translation attempt {trans.attempts} starting.")
            
            # 1. 번역 요청
            translated_raw, is_fallback = await translate_with_llm(job.source_content, lang, feedback_list)
            trans.translated_content = translated_raw
            trans.is_fallback = is_fallback
            db.commit()

            # 2. 정적 린터 검증
            lint_ok, lint_msg = lint_translation(job.source_content, translated_raw)
            if not lint_ok:
                logger.warning(f"Job {job_id} [{lang}] lint failed: {lint_msg}")
                feedback_list.append(f"Attempt {trans.attempts} Lint Error: {lint_msg}")
                trans.lint_status = "FAILED"
                trans.feedback_log = feedback_list
                db.commit()
                continue

            trans.lint_status = "PASSED"
            db.commit()

            if is_fallback:
                trans.qa_status = "UNAVAILABLE"
                trans.quality_score = -1
                feedback_list.append(
                    f"Attempt {trans.attempts}: LLM 연결 실패로 로컬 fallback을 생성했습니다. 승인할 수 없습니다."
                )
                trans.feedback_log = feedback_list
                db.commit()
                break

            # 3. LLM 품질 평가
            q_score, q_critique, qa_availability = await evaluate_quality_with_llm(
                job.source_content, translated_raw, lang
            )
            trans.quality_score = q_score
            trans.qa_status = "UNAVAILABLE" if qa_availability == "UNAVAILABLE" else "PENDING"
            feedback_list.append(f"Attempt {trans.attempts} QA Score: {q_score}. Critique: {q_critique}")
            trans.feedback_log = feedback_list
            db.commit()

            if qa_availability == "UNAVAILABLE":
                break

            # 합격 기준 점수 (85점) 확인
            if q_score >= 85:
                trans.qa_status = "PASSED"
                success = True
                logger.info(f"Job {job_id} [{lang}] successfully passed all checks with score {q_score}.")
                break
            else:
                trans.qa_status = "FAILED"
                db.commit()
                logger.warning(f"Job {job_id} [{lang}] failed quality score ({q_score} < 85). Retrying.")

        if not success:
            logger.error(f"Job {job_id} [{lang}] failed after maximum translation attempts.")

    # 모든 번역 완료 시 잡 상태 변경
    # 모든 번역 중 실패한 항목이 있으면 FAILED, 전부 정상이면 REVIEW_READY
    translations = db.query(Translation).filter(Translation.job_id == job_id).all()
    if any(t.is_fallback or t.qa_status == "UNAVAILABLE" for t in translations):
        job.status = "DEGRADED"
    elif any(t.lint_status == "FAILED" for t in translations):
        job.status = "FAILED"
    elif any(t.qa_status == "FAILED" for t in translations):
        job.status = "QA_FAILED"
    elif all(
        t.lint_status == "PASSED"
        and t.qa_status == "PASSED"
        and t.quality_score >= 85
        and not t.is_fallback
        for t in translations
    ):
        job.status = "REVIEW_READY"
    else:
        job.status = "FAILED"
    
    db.commit()
    logger.info(f"Job {job_id} process finished. Status: {job.status}")
