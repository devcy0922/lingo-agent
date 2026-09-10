import pytest
from pathlib import Path
from lingo.cli import normalize_langs, parse_args


def test_normalize_langs():
    assert normalize_langs(["en", "ja"]) == ["en-US", "ja-JP"]
    assert normalize_langs(["en,ja"]) == ["en-US", "ja-JP"]
    assert normalize_langs(["en-US", "fr-FR"]) == ["en-US", "fr-FR"]
    assert normalize_langs(None) is None


def test_build_parser_options():
    # 1. 단축 옵션 및 target 인자 직접 전달 (자동 translate 보정)
    args = parse_args(["docs/post.md", "-l", "en,ja", "-p", "tech_blog"])
    assert str(args.target) == "docs/post.md"
    assert args.langs == ["en,ja"]
    assert args.profile == "tech_blog"
    assert args.command == "translate"

    # 2. translate 서브커맨드 명시
    args_sub = parse_args(["translate", "locales/ko.json", "--diff"])
    assert args_sub.command == "translate"
    assert str(args_sub.target) == "locales/ko.json"
    assert args_sub.diff is True

    # 3. check 서브커맨드 명시
    args_check = parse_args(["check", "locales/ko.json"])
    assert args_check.command == "check"
    assert str(args_check.target) == "locales/ko.json"
