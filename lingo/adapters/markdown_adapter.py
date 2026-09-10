from __future__ import annotations

import logging
import os
import re
from pathlib import Path
from typing import List, Optional, Tuple

from lingo.adapters.base import BaseAdapter
from lingo.config import LingoConfig
from lingo.engine.client import GatewayClient

logger = logging.getLogger("lingo.adapters.markdown")


def split_markdown(content: str) -> Tuple[str, List[Tuple[str, str]]]:
    """frontmatter와 보호 블록(코드블록, mermaid)을 분리하되 원래 순서를 유지합니다."""
    lines = content.splitlines(keepends=True)
    frontmatter = ""
    start = 0
    if lines and lines[0].strip() == "---":
        end = next((i for i in range(1, len(lines)) if lines[i].strip() == "---"), None)
        if end is None:
            raise ValueError("닫히지 않은 frontmatter")
        frontmatter = "".join(lines[: end + 1])
        start = end + 1

    tokens: List[Tuple[str, str]] = []
    buffer: List[str] = []
    protected_buffer: List[str] = []
    in_fence = False

    def flush() -> None:
        if buffer:
            tokens.append(("body", "".join(buffer)))
            buffer.clear()

    for line in lines[start:]:
        if re.match(r"^\s*```", line):
            if in_fence:
                protected_buffer.append(line)
                in_fence = False
                tokens.append(("protected", "".join(protected_buffer)))
                protected_buffer.clear()
            else:
                flush()
                protected_buffer.append(line)
                in_fence = True
            continue
        if in_fence:
            protected_buffer.append(line)
        else:
            buffer.append(line)

    flush()
    if protected_buffer:
        tokens.append(("protected", "".join(protected_buffer)))

    return frontmatter, tokens


class MarkdownAdapter(BaseAdapter):
    """Markdown 문서의 Frontmatter 및 코드 블록을 보존하는 Fail-Closed 번역 어댑터."""

    def __init__(self, config: LingoConfig):
        super().__init__(config)
        self.client = GatewayClient(
            gateway_url=config.gateway_url,
            api_key=config.api_key,
            timeout=config.timeout,
            min_interval=config.min_interval,
        )

    def _build_system_prompt(self, target_lang: str) -> str:
        profile = self.config.profile
        style = profile.tone.style if profile else "friendly_technical"
        formality = profile.tone.formality if profile else "polite"
        
        guidelines = [
            f"Target Language: {target_lang}",
            f"Tone/Style: {style}, Formality: {formality}",
            "Translate the markdown body accurately while preserving markdown syntax, links, and formatting.",
            "Do NOT add, remove, or modify code blocks or inline backticks.",
            "Do NOT output conversational filler; output only the translated markdown content.",
        ]
        if profile:
            guidelines.extend(profile.tone.guidelines)
            if profile.terms:
                term_lines = [
                    f"- '{term}': {t_obj.translations.get(target_lang, '')}"
                    for term, t_obj in profile.terms.items()
                    if t_obj.translations.get(target_lang)
                ]
                if term_lines:
                    guidelines.append("Enforce the following glossary terms:")
                    guidelines.extend(term_lines)

        return "\n".join(guidelines)

    def translate(
        self,
        source_path: Path,
        target_langs: List[str],
        output_dir: Optional[Path] = None,
        base_source_path: Optional[Path] = None,
        report_path: Optional[Path] = None,
    ) -> int:
        if not source_path.exists():
            logger.error(f"원본 파일을 찾을 수 없습니다: {source_path}")
            return 3

        content = source_path.read_text(encoding="utf-8")
        try:
            frontmatter, tokens = split_markdown(content)
        except Exception as e:
            logger.error(f"Markdown 파싱 오류: {e}")
            return 3

        logger.info(f"Markdown 파싱 완료: frontmatter {len(frontmatter)}자, 블록 {len(tokens)}개")

        for lang in target_langs:
            logger.info(f"[{lang}] 번역 시작...")
            system_prompt = self._build_system_prompt(lang)
            translated_tokens: List[str] = []

            for token_type, text in tokens:
                if token_type == "protected" or not text.strip():
                    translated_tokens.append(text)
                    continue

                # TM 조회
                cached = None
                if self.config.glossary_manager:
                    cached = self.config.glossary_manager.lookup_tm(
                        text, lang, self.config.namespace
                    )

                if cached:
                    logger.info(f"[{lang}] TM 캐시 적중 ({len(text)}자)")
                    translated_tokens.append(cached)
                    continue

                if self.config.dry_run:
                    logger.info(f"[{lang}] [Dry-run] 번역 스킵: {text[:40]}...")
                    translated_tokens.append(text)
                    continue

                # LLM 호출
                messages = [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": text},
                ]
                try:
                    translated_chunk = self.client.chat_completion(
                        model=self.config.translation_model,
                        messages=messages,
                        temperature=0.2,
                    )
                except Exception as e:
                    logger.error(f"[{lang}] 번역 실패 (Fail-Closed): {e}")
                    return 1

                # TM 기록
                if self.config.glossary_manager:
                    self.config.glossary_manager.record_tm(
                        text, lang, self.config.namespace, translated_chunk
                    )

                translated_tokens.append(translated_chunk)

            final_content = frontmatter + "".join(translated_tokens)

            # 출력 경로 결정
            if output_dir:
                out_file = output_dir / lang / source_path.name
            else:
                out_file = source_path.with_name(f"{source_path.stem}.{lang}{source_path.suffix}")

            if not self.config.dry_run:
                out_file.parent.mkdir(parents=True, exist_ok=True)
                out_file.write_text(final_content, encoding="utf-8")
                logger.info(f"[{lang}] 번역 파일 저장 완료: {out_file}")

        # TM 저장
        if self.config.tm_path and self.config.glossary_manager and not self.config.dry_run:
            self.config.glossary_manager.save_tm(self.config.tm_path)

        return 0
