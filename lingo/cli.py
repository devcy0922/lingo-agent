from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path
from typing import List, Optional

from lingo.adapters.json_adapter import JsonAdapter
from lingo.adapters.markdown_adapter import MarkdownAdapter
from lingo.adapters.openapi_adapter import OpenApiAdapter, is_openapi_document
from lingo.config import load_config

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("lingo")

VERSION = "1.3.0"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="lingo",
        description="Lingo: 통합 i18n & Markdown 다국어 번역 에이전트 및 배포 게이트",
    )
    parser.add_argument(
        "-v", "--version", action="version", version=f"%(prog)s {VERSION}"
    )

    subparsers = parser.add_subparsers(dest="command", help="세부 명령")

    # 1. translate 서브커맨드 (기본 명령)
    trans_p = subparsers.add_parser("translate", help="i18n 또는 문서 번역 실행")
    trans_p.add_argument("target", nargs="?", type=Path, help="번역 대상 파일 (예: docs/post.md 또는 locales/ko.json)")
    trans_p.add_argument("--source", type=Path, help="원본 JSON 파일 경로")
    trans_p.add_argument("--base-source", type=Path, help="증분 번역 기준 원본 JSON 파일")
    trans_p.add_argument("-l", "--langs", nargs="+", help="타깃 언어 목록 (예: en ja 또는 en-US ja-JP)")
    trans_p.add_argument("-p", "--profile", type=str, help="적용할 프로필 (예: tech_blog, internal_admin, global)")
    trans_p.add_argument("-o", "--output", type=Path, help="출력 디렉토리")
    trans_p.add_argument("-c", "--config", type=Path, help="설정 파일 경로 (.lingo.yml)")
    trans_p.add_argument("--diff", action="store_true", help="Git HEAD 대비 변경된 키/내용만 증분 번역")
    trans_p.add_argument("--sync-all", action="store_true", help="전체 재번역 강제")
    trans_p.add_argument("--dry-run", action="store_true", help="드라이런")
    trans_p.add_argument("--report", type=Path, default=Path("lingo-report.json"), help="QA 보고서 경로")
    trans_p.add_argument("--runtime", type=str, default="langgraph", choices=["langgraph", "engine-process", "mock"], help="번역 오케스트레이션 런타임 엔진 선택")

    # 2. check 서브커맨드 (CI 검증 전용)
    check_p = subparsers.add_parser("check", help="CI 검증 전용 (린트 및 QA 통과 확인)")
    check_p.add_argument("target", type=Path, help="검증할 원본 파일")
    check_p.add_argument("-l", "--langs", nargs="+", help="타깃 언어 목록")
    check_p.add_argument("-o", "--output", type=Path, help="타깃 파일이 있는 디렉토리")
    check_p.add_argument("-p", "--profile", type=str, help="적용할 프로필")
    check_p.add_argument("-c", "--config", type=Path, help="설정 파일 경로 (.lingo.yml)")

    return parser


def preprocess_argv(argv: Optional[List[str]]) -> List[str]:
    """첫 인자가 서브커맨드가 아니거나 파일 경로/플래그인 경우 'translate'를 기본 서브커맨드로 보정합니다."""
    args = list(argv) if argv is not None else sys.argv[1:]
    if not args:
        return args

    known_subcommands = {"translate", "check", "-h", "--help", "-v", "--version"}
    if args[0] not in known_subcommands:
        args = ["translate"] + args
    return args


def normalize_langs(raw_langs: Optional[List[str]]) -> Optional[List[str]]:
    if not raw_langs:
        return None
    result: List[str] = []
    for l in raw_langs:
        for part in l.split(","):
            part = part.strip()
            if not part:
                continue
            if part.lower() == "en":
                result.append("en-US")
            elif part.lower() == "ja":
                result.append("ja-JP")
            else:
                result.append(part)
    return result


def parse_args(argv: Optional[List[str]] = None) -> argparse.Namespace:
    parser = build_parser()
    adjusted_argv = preprocess_argv(argv)
    return parser.parse_args(adjusted_argv)


def main(argv: Optional[List[str]] = None) -> int:
    parser = build_parser()
    adjusted_argv = preprocess_argv(argv)
    args = parser.parse_args(adjusted_argv)


    # 서브커맨드와 루트 인자 통합
    target_path = getattr(args, "path", None) or getattr(args, "source", None) or args.target
    raw_langs = getattr(args, "langs", None)
    target_langs = normalize_langs(raw_langs)
    profile_name = getattr(args, "profile", None)
    output_dir = getattr(args, "output", None)
    diff_mode = bool(getattr(args, "diff", False))
    base_source = getattr(args, "base_source", None)
    sync_all = bool(getattr(args, "sync_all", False))
    dry_run = bool(getattr(args, "dry_run", False))
    report_path = getattr(args, "report", Path("lingo-report.json"))
    config_path = getattr(args, "config", None)
    runtime_choice = getattr(args, "runtime", None)
    if runtime_choice:
        import os
        os.environ["LINGO_RUNTIME_PROVIDER"] = runtime_choice

    # check 명령인 경우 dry-run 강제
    if args.command == "check":
        dry_run = True

    if not target_path:
        # CWD에서 ko.json 또는 기본 파일 탐색 시도
        cwd_ko = Path.cwd() / "ko.json"
        locales_ko = Path.cwd() / "locales" / "ko.json"
        if cwd_ko.exists():
            target_path = cwd_ko
        elif locales_ko.exists():
            target_path = locales_ko
        else:
            parser.print_help()
            return 1

    # 설정 로드
    config = load_config(
        config_path=config_path,
        profile_override=profile_name,
        langs_override=target_langs,
        dry_run=dry_run,
    )

    resolved_langs = target_langs or config.target_langs
    resolved_output = output_dir or target_path.parent

    logger.info(f"Lingo v{VERSION} 가동: 대상={target_path.name}, 프로필={config.profile_name}, 언어={resolved_langs}")

    # 확장자 자동 감지 및 어댑터 분기
    suffix = target_path.suffix.lower()
    if suffix in [".md", ".markdown"]:
        adapter = MarkdownAdapter(config)
        return adapter.translate(
            source_path=target_path,
            target_langs=resolved_langs,
            output_dir=output_dir,
            report_path=report_path,
        )
    elif suffix in [".json"]:
        if is_openapi_document(target_path):
            adapter = OpenApiAdapter(config)
        else:
            adapter = JsonAdapter(config)
        return adapter.translate(
            source_path=target_path,
            target_langs=resolved_langs,
            output_dir=resolved_output,
            base_source_path=base_source,
            report_path=report_path,
            sync_all=sync_all,
            use_git_diff=diff_mode,
        )
    else:
        logger.error(f"지원하지 않는 파일 형식입니다: {suffix} (.json 또는 .md 지원)")
        return 3


if __name__ == "__main__":
    sys.exit(main())
