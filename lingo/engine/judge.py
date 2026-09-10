from __future__ import annotations

import json
import logging
from typing import Any, Dict, List, Optional

from lingo.engine.client import GatewayClient
from lingo.types import BatchQAResult, KeyQAResult, ProfileConfig

logger = logging.getLogger("lingo.engine.judge")

QA_PROMPT_TEMPLATE = """You are a rigorous translation QA evaluator for software and documentation.
Source Language: Korean (ko-KR)
Target Language: {target_lang}
Profile Style: {profile_style} ({profile_formality})

Evaluate the following translations.
Items to evaluate:
{items_json}

Return ONLY a valid JSON object matching this exact structure:
{{
  "results": [
    {{
      "key": "<key_name>",
      "scores": {{
        "semantic_accuracy": <1-5>,
        "naturalness": <1-5>,
        "terminology": <1-5>,
        "ui_fit": <1-5>
      }},
      "critique": "<brief feedback>",
      "critical_error": <true/false>
    }}
  ]
}}
"""


class QAJudge:
    def __init__(self, client: GatewayClient, model: str = "govail/thinker"):
        self.client = client
        self.model = model

    def evaluate_batch(
        self,
        batch_items: List[Dict[str, str]],
        target_lang: str,
        profile: Optional[ProfileConfig] = None,
    ) -> BatchQAResult:
        """한 배치의 번역 항목들을 LLM 심사위원으로 평가합니다."""
        if not batch_items:
            return BatchQAResult(passed=True)

        style = profile.tone.style if profile else "general"
        formality = profile.tone.formality if profile else "polite"

        prompt = QA_PROMPT_TEMPLATE.format(
            target_lang=target_lang,
            profile_style=style,
            profile_formality=formality,
            items_json=json.dumps(batch_items, ensure_ascii=False, indent=2),
        )

        messages = [
            {"role": "system", "content": "You are a professional localization QA judge. Return strict JSON only."},
            {"role": "user", "content": prompt},
        ]

        try:
            raw_resp = self.client.chat_completion(self.model, messages, temperature=0.1)
            # JSON 파싱
            clean_json = raw_resp
            if "```json" in clean_json:
                clean_json = clean_json.split("```json")[1].split("```")[0].strip()
            elif "```" in clean_json:
                clean_json = clean_json.split("```")[1].split("```")[0].strip()

            parsed = json.loads(clean_json)
            raw_results = parsed.get("results", [])

            key_results: Dict[str, KeyQAResult] = {}
            all_passed = True
            total_score = 0.0
            count = 0

            for res in raw_results:
                k = res.get("key", "")
                scores = res.get("scores", {})
                critique = res.get("critique", "")
                crit_err = bool(res.get("critical_error", False))

                sem = scores.get("semantic_accuracy", 3)
                nat = scores.get("naturalness", 3)
                term = scores.get("terminology", 4)
                ui = scores.get("ui_fit", 3)
                avg = (sem + nat + term + ui) / 4.0

                total_score += avg
                count += 1

                # 판정 기준: 용어>=4, 의미>=3, 평균>=3.5, critical_error 없음
                passed = (term >= 4) and (sem >= 3) and (avg >= 3.5) and not crit_err
                if not passed:
                    all_passed = False

                key_results[k] = KeyQAResult(
                    key=k,
                    scores=scores,
                    critiques={k: critique},
                    passed=passed,
                    critical_error=crit_err,
                )

            batch_avg = (total_score / count) if count > 0 else 0.0
            return BatchQAResult(
                key_results=key_results,
                passed=all_passed,
                average_score=batch_avg,
            )
        except Exception as e:
            logger.error(f"QA Judge evaluation failed: {e}")
            # Fail-closed
            raise RuntimeError(f"QA 평가 실패 (Fail-Closed): {e}")
