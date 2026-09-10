import pytest
from pathlib import Path
from lingo.adapters.markdown_adapter import split_markdown
from lingo.adapters.json_adapter import JsonAdapter
from lingo.config import LingoConfig
from lingo.types import ProfileConfig, GlossaryTerm


def test_split_markdown_preserves_code_and_mermaid():
    md = """---
title: Test Post
date: 2026-09-11
---

안녕하세요. 이것은 테스트입니다.

```python
def hello():
    return "world"
```

다음 문단입니다.

```mermaid
graph TD;
    A-->B;
```
"""
    frontmatter, tokens = split_markdown(md)

    assert "title: Test Post" in frontmatter
    assert len(tokens) == 4

    kinds = [k for k, _ in tokens]
    assert kinds == ["body", "protected", "body", "protected"]

    # code block & mermaid block intact
    assert 'def hello():' in tokens[1][1]
    assert 'graph TD;' in tokens[3][1]


def test_json_adapter_converts_profile_terms():
    profile = ProfileConfig(
        name="test",
        terms={
            "워크스페이스": GlossaryTerm(
                term="워크스페이스",
                translations={"en-US": "Workspace", "ja-JP": "ワークスペース"},
                forbidden=["작업공간"],
            )
        },
        prohibited_phrases=["클릭하세요"],
    )
    config = LingoConfig(profile=profile, target_langs=["en-US", "ja-JP"])
    adapter = JsonAdapter(config)
    glossary = adapter._convert_profile_to_glossary()

    assert "클릭하세요" in glossary["preserve"]
    assert len(glossary["entries"]) == 1
    entry = glossary["entries"][0]
    assert entry["source"] == "워크스페이스"
    assert entry["targets"]["en-US"] == "Workspace"
    assert entry["forbidden"]["en-US"] == ["작업공간"]
