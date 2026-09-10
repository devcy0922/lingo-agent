from __future__ import annotations

import json
import logging
import subprocess
from pathlib import Path
from typing import Any, Dict, List, Optional

import sys

from lingo.adapters.base import BaseAdapter
from lingo.config import LingoConfig

try:
    import translate
except ImportError:
    repo_root = Path(__file__).resolve().parents[2]
    if str(repo_root) not in sys.path:
        sys.path.insert(0, str(repo_root))
    import translate

logger = logging.getLogger("lingo.adapters.json")


class JsonAdapter(BaseAdapter):
    """JSON i18n 로케일 파일의 증분 번역 및 QA 배포 게이트 어댑터."""

    def _convert_profile_to_glossary(self) -> Dict[str, Any]:
        """LingoConfig의 Profile 설정을 translate.py 호환 glossary 딕셔너리로 변환합니다."""
        glossary: Dict[str, Any] = {"preserve": [], "entries": []}
        profile = self.config.profile
        if not profile:
            return glossary

        glossary["preserve"] = list(profile.prohibited_phrases)

        for term, term_obj in profile.terms.items():
            forbidden_map: Dict[str, List[str]] = {}
            if term_obj.forbidden:
                for lang in self.config.target_langs:
                    forbidden_map[lang] = term_obj.forbidden

            glossary["entries"].append({
                "source": term,
                "targets": term_obj.translations,
                "forbidden": forbidden_map,
                "note": term_obj.note,
            })

        return glossary

    def _resolve_base_source_from_git(self, source_path: Path) -> Optional[str]:
        """--diff 옵션 시 Git HEAD 기준으로 이전 버전의 JSON 문자열을 가져옵니다."""
        try:
            cmd = ["git", "show", f"HEAD:{source_path}"]
            res = subprocess.run(cmd, capture_output=True, text=True, check=True)
            return res.stdout
        except Exception as e:
            logger.warning(f"Git HEAD에서 이전 소스를 가져오지 못했습니다: {e}")
            return None

    def translate(
        self,
        source_path: Path,
        target_langs: List[str],
        output_dir: Optional[Path] = None,
        base_source_path: Optional[Path] = None,
        report_path: Optional[Path] = None,
        sync_all: bool = False,
        use_git_diff: bool = False,
    ) -> int:
        if not source_path.exists():
            logger.error(f"원본 파일을 찾을 수 없습니다: {source_path}")
            return 3

        try:
            source = translate._load_json(source_path, required=True)
        except Exception as e:
            logger.error(f"JSON 파싱 실패 ({source_path}): {e}")
            return 3

        base_content = None
        if base_source_path and base_source_path.exists():
            base_json = translate._load_json(base_source_path)
            base_content = json.dumps(base_json, ensure_ascii=False)
        elif use_git_diff:
            base_content = self._resolve_base_source_from_git(source_path)

        source_content = json.dumps(source, ensure_ascii=False)
        glossary = self._convert_profile_to_glossary()

        out_dir = output_dir or source_path.parent
        results: List[translate.TranslationResult] = []

        for lang in target_langs:
            lang_code = lang.split("-")[0]
            output_file = out_dir / f"{lang_code}.json"
            existing_content = "{}"
            if output_file.exists():
                try:
                    existing_json = translate._load_json(output_file)
                    existing_content = json.dumps(existing_json, ensure_ascii=False)
                except Exception:
                    pass

            logger.info(f"[{lang}] 번역 파이프라인 가동 (타깃: {output_file.name})...")
            result = translate.run_pipeline(
                source_content=source_content,
                target_lang=lang,
                existing_content=existing_content,
                base_source_content=base_content,
                glossary=glossary,
                sync_all=sync_all,
            )
            results.append(result)
            logger.info(
                f"[{lang}] 완료: selected={len(result.scope.selected)}, "
                f"preserved={len(result.scope.preserved)}, QA={result.qa_status}, score={result.qa_score}"
            )

        # 보고서 작성
        actual_report_path = report_path or Path("lingo-report.json")
        try:
            # translate._write_report 호환 객체
            class DummyArgs:
                source = source_path
                base_source = base_source_path
                sync_all = sync_all
            translate._write_report(actual_report_path, results, DummyArgs())
            logger.info(f"QA 보고서 작성 완료: {actual_report_path}")
        except Exception as e:
            logger.warning(f"QA 보고서 작성 실패: {e}")

        failed = [r.lang for r in results if not r.success]
        if failed:
            logger.error(f"COMMIT BLOCKED: 검증 실패 언어: {failed}")
            return 1 if any(r.is_fallback for r in results) else 2

        if not self.config.dry_run:
            out_dir.mkdir(parents=True, exist_ok=True)
            for r in results:
                lang_code = r.lang.split("-")[0]
                save_path = out_dir / f"{lang_code}.json"
                save_path.write_text(r.content + "\n", encoding="utf-8")
                logger.info(f"[{r.lang}] 번역 파일 저장 완료: {save_path}")

        logger.info("모든 JSON 번역 및 품질 검증 통과!")
        return 0
