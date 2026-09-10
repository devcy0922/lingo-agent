#!/usr/bin/env python3
"""Markdown 문서의 구조를 보존하는 LLM 번역 adapter.

frontmatter와 fenced code/Mermaid 블록은 그대로 보존하고, 나머지 Markdown
본문만 모델에 전달한다. Gateway 장애나 잘못된 응답은 fallback하지 않고 실패한다.
"""

from __future__ import annotations

import argparse
import os
import re
from pathlib import Path

import httpx


MODEL = os.environ.get("LLM_MARKDOWN_MODEL", "govail/thinker")
GATEWAY_URL = os.environ.get("LLM_GATEWAY_URL", "").rstrip("/")
API_KEY = os.environ.get("LLM_API_KEY", "")
TIMEOUT = float(os.environ.get("LLM_TIMEOUT_SECONDS", "240"))


def _split_markdown(content: str) -> tuple[str, list[tuple[str, str]]]:
    """frontmatter와 보호 블록을 분리하되 원래 순서를 유지한다."""
    lines = content.splitlines(keepends=True)
    frontmatter = ""
    start = 0
    if lines and lines[0].strip() == "---":
        end = next((i for i in range(1, len(lines)) if lines[i].strip() == "---"), None)
        if end is None:
            raise ValueError("닫히지 않은 frontmatter")
        frontmatter = "".join(lines[: end + 1])
        start = end + 1

    tokens: list[tuple[str, str]] = []
    buffer: list[str] = []
    protected_buffer: list[str] = []
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
    if in_fence:
        raise ValueError("닫히지 않은 fenced code block")
    flush()
    return frontmatter, tokens


def _prompt(source: str, target_lang: str) -> str:
    return (
        f"Translate this Korean Markdown document into {target_lang}.\n"
        "Return Markdown only. Preserve heading levels, list structure, inline code, "
        "URLs, file paths, identifiers, and HTML tags exactly. Do not add commentary.\n\n"
        f"SOURCE:\n{source}"
    )


def translate_segment(source: str, target_lang: str) -> str:
    if not GATEWAY_URL or not API_KEY:
        raise RuntimeError("LLM_GATEWAY_URL and LLM_API_KEY are required")
    response = httpx.post(
        f"{GATEWAY_URL}/chat/completions",
        headers={"Authorization": f"Bearer {API_KEY}"},
        json={
            "model": MODEL,
            "messages": [
                {"role": "system", "content": "You are a strict technical localization editor."},
                {"role": "user", "content": _prompt(source, target_lang)},
            ],
            "temperature": 0.1,
        },
        timeout=TIMEOUT,
    )
    response.raise_for_status()
    payload = response.json()
    content = payload["choices"][0]["message"]["content"]
    if not isinstance(content, str) or not content.strip():
        raise ValueError("empty Markdown translation")
    # 모델이 문단 양끝의 개행을 정리해도 Markdown token 경계는 원문과 동일하게 유지한다.
    prefix = re.match(r"^\s*", source, re.DOTALL).group(0)
    suffix = re.search(r"\s*$", source, re.DOTALL).group(0)
    core = content.strip()
    return prefix + core + suffix


def translate_file(source_path: Path, output_path: Path, target_lang: str) -> None:
    source = source_path.read_text(encoding="utf-8")
    frontmatter, tokens = _split_markdown(source)
    result = frontmatter
    for kind, value in tokens:
        result += translate_segment(value, target_lang) if kind == "body" else value
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(result, encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--lang", required=True)
    args = parser.parse_args()
    translate_file(args.source, args.output, args.lang)


if __name__ == "__main__":
    main()
