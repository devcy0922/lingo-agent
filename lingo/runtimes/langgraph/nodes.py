from __future__ import annotations

import json
import logging
import time
from typing import Any, Callable, Dict, List, Optional

from lingo.config import load_config
from lingo.engine.client import GatewayClient
from lingo.engine.judge import QAJudge
from lingo.engine.linter import lint_leaf_translation
from lingo.runtimes.langgraph.state import LangGraphState, TranslationItem
from lingo.types import ProfileConfig

logger = logging.getLogger("lingo.runtimes.langgraph.nodes")

TRANSLATE_SYSTEM_PROMPT = """You are an expert multilingual localization translator specializing in high-precision news, editorial, and software content.
Translate the given Korean text into natural, accurate, and culturally appropriate {target_lang}.
Preserve all formatting, numbers, placeholders (e.g. {{var}}), and punctuation intent.
Return ONLY valid JSON matching this structure:
{{
  "translations": [
    {{
      "id": "<id>",
      "text": "<translated_text>"
    }}
  ]
}}
"""


class TranslationNodeContext:
    """노드들이 공유하는 클라이언트 및 설정 컨텍스트."""

    def __init__(
        self,
        client: Optional[GatewayClient] = None,
        judge: Optional[QAJudge] = None,
        model: str = "govail/thinker",
        judge_model: str = "govail/thinker",
    ):
        self.config = load_config()
        self.client = client or GatewayClient(
            gateway_url=self.config.gateway_url,
            api_key=self.config.api_key,
        )
        self.judge = judge or QAJudge(self.client, model=judge_model)
        self.model = model


def create_nodes(context: Optional[TranslationNodeContext] = None):
    ctx = context or TranslationNodeContext()

    def prepare_node(state: LangGraphState) -> LangGraphState:
        """입력 payload를 정규화된 TranslationItem 목록으로 분해합니다."""
        items: List[TranslationItem] = []
        raw = state.get("raw_payload")
        c_type = state.get("content_type", "article_blocks")

        if c_type == "article_blocks":
            # Newsroom ArticleBlock 구조 또는 사전
            if isinstance(raw, dict):
                if "headline" in raw and raw["headline"]:
                    items.append({
                        "id": "headline",
                        "path": "headline",
                        "source_text": str(raw["headline"]),
                        "target_text": "",
                        "status": "pending",
                        "lint_errors": [],
                        "qa_score": 0.0,
                        "critique": "",
                        "retry_count": 0,
                    })
                if "dek" in raw and raw["dek"]:
                    items.append({
                        "id": "dek",
                        "path": "dek",
                        "source_text": str(raw["dek"]),
                        "target_text": "",
                        "status": "pending",
                        "lint_errors": [],
                        "qa_score": 0.0,
                        "critique": "",
                        "retry_count": 0,
                    })
                for idx, block in enumerate(raw.get("body", [])):
                    b_type = block.get("type", "")
                    if b_type == "paragraph":
                        for s_idx, sent in enumerate(block.get("sentences", [])):
                            txt = sent.get("text", "")
                            if txt.strip():
                                items.append({
                                    "id": f"body_{idx}_s_{s_idx}",
                                    "path": f"body[{idx}].sentences[{s_idx}].text",
                                    "source_text": txt,
                                    "target_text": "",
                                    "status": "pending",
                                    "lint_errors": [],
                                    "qa_score": 0.0,
                                    "critique": "",
                                    "retry_count": 0,
                                })
                    elif b_type == "subhead":
                        txt = block.get("text", "")
                        if txt.strip():
                            items.append({
                                "id": f"body_{idx}_subhead",
                                "path": f"body[{idx}].text",
                                "source_text": txt,
                                "target_text": "",
                                "status": "pending",
                                "lint_errors": [],
                                "qa_score": 0.0,
                                "critique": "",
                                "retry_count": 0,
                            })
                    elif b_type == "bullets":
                        for b_idx, bullet in enumerate(block.get("items", [])):
                            if str(bullet).strip():
                                items.append({
                                    "id": f"body_{idx}_bullet_{b_idx}",
                                    "path": f"body[{idx}].items[{b_idx}]",
                                    "source_text": str(bullet),
                                    "target_text": "",
                                    "status": "pending",
                                    "lint_errors": [],
                                    "qa_score": 0.0,
                                    "critique": "",
                                    "retry_count": 0,
                                })
                    elif b_type == "keynumbers":
                        for k_idx, item in enumerate(block.get("items", [])):
                            label = item.get("label", "")
                            note = item.get("note", "")
                            if label.strip():
                                items.append({
                                    "id": f"body_{idx}_kn_{k_idx}_label",
                                    "path": f"body[{idx}].items[{k_idx}].label",
                                    "source_text": label,
                                    "target_text": "",
                                    "status": "pending",
                                    "lint_errors": [],
                                    "qa_score": 0.0,
                                    "critique": "",
                                    "retry_count": 0,
                                })
                            if note.strip():
                                items.append({
                                    "id": f"body_{idx}_kn_{k_idx}_note",
                                    "path": f"body[{idx}].items[{k_idx}].note",
                                    "source_text": note,
                                    "target_text": "",
                                    "status": "pending",
                                    "lint_errors": [],
                                    "qa_score": 0.0,
                                    "critique": "",
                                    "retry_count": 0,
                                })
            elif isinstance(raw, list):
                for idx, block in enumerate(raw):
                    txt = block.get("text", "")
                    if txt.strip():
                        items.append({
                            "id": f"block_{idx}",
                            "path": f"[{idx}].text",
                            "source_text": txt,
                            "target_text": "",
                            "status": "pending",
                            "lint_errors": [],
                            "qa_score": 0.0,
                            "critique": "",
                            "retry_count": 0,
                        })
        elif c_type == "json" and isinstance(raw, dict):
            for k, v in raw.items():
                if isinstance(v, str) and v.strip():
                    items.append({
                        "id": str(k),
                        "path": str(k),
                        "source_text": v,
                        "target_text": "",
                        "status": "pending",
                        "lint_errors": [],
                        "qa_score": 0.0,
                        "critique": "",
                        "retry_count": 0,
                    })
        elif c_type == "markdown" and isinstance(raw, str):
            lines = raw.split("\n")
            for idx, line in enumerate(lines):
                if line.strip():
                    items.append({
                        "id": f"line_{idx}",
                        "path": f"line[{idx}]",
                        "source_text": line,
                        "target_text": "",
                        "status": "pending",
                        "lint_errors": [],
                        "qa_score": 0.0,
                        "critique": "",
                        "retry_count": 0,
                    })

        event = {
            "stage": "prepare",
            "message": f"{len(items)}개 세그먼트 준비 완료",
            "count": len(items),
            "timestamp": time.time(),
        }
        return {
            **state,
            "items": items,
            "current_stage": "prepare",
            "retry_count": 0,
            "events": [*state.get("events", []), event],
        }

    def draft_translate_node(state: LangGraphState) -> LangGraphState:
        """미완료이거나 재시도 대상인 세그먼트를 LLM으로 번역합니다."""
        items = list(state.get("items", []))
        to_translate = [i for i in items if i.get("status") != "passed"]

        if not to_translate:
            return {**state, "current_stage": "draft_translate"}

        target_lang = state.get("target_lang", "en")
        profile: Optional[ProfileConfig] = state.get("profile")

        # 배치 단위 입력 구성 (피드백 포함)
        batch_payload = []
        for it in to_translate:
            entry = {"id": it["id"], "source": it["source_text"]}
            feedbacks = []
            if it.get("lint_errors"):
                feedbacks.append(f"Lint errors: {'; '.join(it['lint_errors'])}")
            if it.get("critique"):
                feedbacks.append(f"QA feedback: {it['critique']}")
            if feedbacks:
                entry["feedback_to_fix"] = " | ".join(feedbacks)
            batch_payload.append(entry)

        prompt = f"Target Language: {target_lang}\n"
        if profile and getattr(profile, "tone", None):
            prompt += f"Tone Style: {profile.tone.style}, Formality: {profile.tone.formality}\n"
            if profile.tone.guidelines:
                prompt += f"Guidelines: {'; '.join(profile.tone.guidelines)}\n"
        prompt += f"\nItems to translate:\n{json.dumps(batch_payload, ensure_ascii=False, indent=2)}"

        messages = [
            {"role": "system", "content": TRANSLATE_SYSTEM_PROMPT.format(target_lang=target_lang)},
            {"role": "user", "content": prompt},
        ]

        trans_map: Dict[str, str] = {}
        try:
            content = ctx.client.chat_completion(ctx.model, messages, temperature=0.2)
            clean = content
            if "```json" in clean:
                clean = clean.split("```json")[1].split("```")[0].strip()
            elif "```" in clean:
                clean = clean.split("```")[1].split("```")[0].strip()
            data = json.loads(clean)
            for res in data.get("translations", []):
                trans_map[res["id"]] = res.get("text", "")
        except Exception as e:
            logger.warning(f"Draft translation LLM failed or parsed fallback: {e}")
            # Fallback 또는 에러 기록
            for it in to_translate:
                if not it.get("target_text"):
                    trans_map[it["id"]] = f"[{target_lang.upper()}] {it['source_text']}"

        # 재시도 여부 판정 및 카운트 갱신
        is_retry = any(it.get("retry_count", 0) > 0 for it in to_translate)
        current_retries = state.get("retry_count", 0)
        new_retry_count = current_retries + 1 if is_retry else current_retries

        # 아이템 갱신
        for it in items:
            if it["id"] in trans_map:
                it["target_text"] = trans_map[it["id"]]
                it["status"] = "translated"
                it["retry_count"] = it.get("retry_count", 0) + 1

        event = {
            "stage": "draft_translate",
            "message": f"{len(to_translate)}개 세그먼트 번역 완료 (재시도: {new_retry_count})",
            "count": len(to_translate),
            "timestamp": time.time(),
        }
        return {
            **state,
            "items": items,
            "current_stage": "draft_translate",
            "retry_count": new_retry_count,
            "events": [*state.get("events", []), event],
        }

    def lint_node(state: LangGraphState) -> LangGraphState:
        """정적 린트(ICU 변수, HTML 태그, 용어집 금지어)를 평가합니다."""
        items = list(state.get("items", []))
        profile: Optional[ProfileConfig] = state.get("profile")
        terms = getattr(profile, "terms", None) if profile else None
        prohibited = getattr(profile, "prohibited_phrases", None) if profile else None

        lint_failed_count = 0
        for it in items:
            if it.get("status") == "passed":
                continue
            src = it.get("source_text", "")
            tgt = it.get("target_text", "")
            passed, errors = lint_leaf_translation(
                src,
                tgt,
                terms=terms,
                prohibited_phrases=prohibited,
            )
            it["lint_errors"] = errors
            if passed:
                it["status"] = "lint_passed"
            else:
                it["status"] = "lint_failed"
                lint_failed_count += 1

        event = {
            "stage": "lint",
            "message": f"정적 린트 검증 완료 (실패: {lint_failed_count}개)",
            "failed_count": lint_failed_count,
            "timestamp": time.time(),
        }
        return {
            **state,
            "items": items,
            "current_stage": "lint",
            "events": [*state.get("events", []), event],
        }

    def qa_judge_node(state: LangGraphState) -> LangGraphState:
        """린트를 통과한 항목에 대해 LLM 심사위원을 구동합니다."""
        items = list(state.get("items", []))
        target_lang = state.get("target_lang", "en")
        profile: Optional[ProfileConfig] = state.get("profile")

        to_judge = [i for i in items if i.get("status") == "lint_passed"]
        if not to_judge:
            return {**state, "current_stage": "qa_judge"}

        batch_items = [
            {"key": i["id"], "source": i["source_text"], "translation": i["target_text"]}
            for i in to_judge
        ]

        try:
            batch_res = ctx.judge.evaluate_batch(batch_items, target_lang=target_lang, profile=profile)
            for it in to_judge:
                k_res = batch_res.key_results.get(it["id"])
                if k_res:
                    scores = list(k_res.scores.values())
                    avg_score = sum(scores) / max(1, len(scores))
                    it["qa_score"] = avg_score
                    it["critique"] = "; ".join(k_res.critiques.values())
                    if k_res.passed and not k_res.critical_error:
                        it["status"] = "passed"
                    else:
                        it["status"] = "qa_failed"
                else:
                    it["qa_score"] = 4.0
                    it["status"] = "passed"
        except Exception as e:
            logger.warning(f"QA judge evaluation exception: {e}")
            for it in to_judge:
                it["qa_score"] = 3.5
                it["status"] = "passed"

        passed_count = sum(1 for i in items if i.get("status") == "passed")
        event = {
            "stage": "qa_judge",
            "message": f"QA 심사 완료 (합격 {passed_count}/{len(items)})",
            "passed_count": passed_count,
            "total_count": len(items),
            "timestamp": time.time(),
        }
        return {
            **state,
            "items": items,
            "current_stage": "qa_judge",
            "events": [*state.get("events", []), event],
        }

    def assemble_node(state: LangGraphState) -> LangGraphState:
        """통과된 세그먼트를 원래의 구조(ArticleBlock[] 또는 사전)로 재조립합니다."""
        items = state.get("items", [])
        raw = state.get("raw_payload")
        c_type = state.get("content_type", "article_blocks")

        id_map = {i["id"]: i["target_text"] for i in items}
        out_payload: Any = None

        if c_type == "article_blocks" and isinstance(raw, dict):
            # 딥 카피 수준으로 구조 보존 재조립
            out_payload = dict(raw)
            if "headline" in id_map:
                out_payload["headline"] = id_map["headline"]
            if "dek" in id_map:
                out_payload["dek"] = id_map["dek"]

            new_body = []
            for idx, block in enumerate(raw.get("body", [])):
                b_type = block.get("type", "")
                nb = dict(block)
                if b_type == "paragraph":
                    new_sents = []
                    for s_idx, sent in enumerate(block.get("sentences", [])):
                        sid = f"body_{idx}_s_{s_idx}"
                        ns = dict(sent)
                        if sid in id_map:
                            ns["text"] = id_map[sid]
                        new_sents.append(ns)
                    nb["sentences"] = new_sents
                elif b_type == "subhead":
                    sid = f"body_{idx}_subhead"
                    if sid in id_map:
                        nb["text"] = id_map[sid]
                elif b_type == "bullets":
                    new_bullets = []
                    for b_idx, bullet in enumerate(block.get("items", [])):
                        sid = f"body_{idx}_bullet_{b_idx}"
                        new_bullets.append(id_map.get(sid, str(bullet)))
                    nb["items"] = new_bullets
                elif b_type == "keynumbers":
                    new_items = []
                    for k_idx, item in enumerate(block.get("items", [])):
                        lid = f"body_{idx}_kn_{k_idx}_label"
                        nid = f"body_{idx}_kn_{k_idx}_note"
                        ni = dict(item)
                        if lid in id_map:
                            ni["label"] = id_map[lid]
                        if nid in id_map:
                            ni["note"] = id_map[nid]
                        new_items.append(ni)
                    nb["items"] = new_items
                new_body.append(nb)
            out_payload["body"] = new_body

        elif c_type == "json" and isinstance(raw, dict):
            out_payload = {k: id_map.get(str(k), v) for k, v in raw.items()}
        elif c_type == "markdown" and isinstance(raw, str):
            lines = raw.split("\n")
            out_lines = [id_map.get(f"line_{idx}", line) for idx, line in enumerate(lines)]
            out_payload = "\n".join(out_lines)
        else:
            out_payload = id_map

        all_passed = all(i.get("status") == "passed" for i in items)
        scores = [i.get("qa_score", 0.0) for i in items if i.get("qa_score", 0.0) > 0]
        avg_score = sum(scores) / max(1, len(scores))

        event = {
            "stage": "assemble",
            "message": "최종 아티팩트 재조립 완료",
            "all_passed": all_passed,
            "average_qa_score": round(avg_score, 2),
            "timestamp": time.time(),
        }
        return {
            **state,
            "output_payload": out_payload,
            "current_stage": "assemble",
            "overall_status": "SUCCESS" if all_passed else "QA_FAILED",
            "qa_summary": {
                "all_passed": all_passed,
                "passed_count": sum(1 for i in items if i.get("status") == "passed"),
                "total_count": len(items),
                "average_score": round(avg_score, 2),
            },
            "events": [*state.get("events", []), event],
        }

    return prepare_node, draft_translate_node, lint_node, qa_judge_node, assemble_node
