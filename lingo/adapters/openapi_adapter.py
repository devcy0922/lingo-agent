from __future__ import annotations

import copy
import json
import logging
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

from lingo.adapters.base import BaseAdapter
from lingo.adapters.json_adapter import JsonAdapter
from lingo.config import LingoConfig

try:
    import translate
except ImportError:
    repo_root = Path(__file__).resolve().parents[2]
    if str(repo_root) not in sys.path:
        sys.path.insert(0, str(repo_root))
    import translate

logger = logging.getLogger("lingo.adapters.openapi")

# OpenAPI 문서에서 실제 자연어로 취급하는 필드만 번역 대상으로 삼는다.
# type, format, $ref, enum 값, 파라미터/스키마 이름 등 구조적 문자열은 건드리지 않는다.
TRANSLATABLE_KEYS = {"description", "summary", "title"}

PathKey = tuple  # tuple[str, ...] — translate.py의 PathKey와 동일한 표기 규약


def is_openapi_document(path: Path) -> bool:
    """파일이 OpenAPI 3.x 스펙 문서인지(단순 i18n locale JSON이 아닌지) 판별합니다."""
    try:
        data = translate._load_json(path, required=True)
    except Exception:
        return False
    return isinstance(data, dict) and "openapi" in data and "paths" in data


def _extract_translatable(obj: Any, path: PathKey = ()) -> Dict[PathKey, str]:
    """OpenAPI 문서를 순회하며 description/summary/title 값만 경로 tuple로 평탄화합니다.

    dict와 list를 모두 재귀 순회한다(translate.py의 _leaf_map은 dict만 순회하므로
    OpenAPI의 리스트 기반 구조 — parameters, tags, examples 등 — 는 여기서 별도 처리한다).
    """
    result: Dict[PathKey, str] = {}
    if isinstance(obj, dict):
        for key, value in obj.items():
            child_path = path + (key,)
            if isinstance(value, str):
                if key in TRANSLATABLE_KEYS and value.strip():
                    result[child_path] = value
            else:
                result.update(_extract_translatable(value, child_path))
    elif isinstance(obj, list):
        for index, item in enumerate(obj):
            result.update(_extract_translatable(item, path + (str(index),)))
    return result


def _apply_translations(original: Any, translations: Dict[PathKey, str]) -> Any:
    """원본 OpenAPI 구조를 복제한 뒤, 번역된 leaf만 해당 경로에 덮어씁니다."""
    doc = copy.deepcopy(original)
    for path, value in translations.items():
        cursor = doc
        for segment in path[:-1]:
            cursor = cursor[int(segment)] if isinstance(cursor, list) else cursor[segment]
        last = path[-1]
        if isinstance(cursor, list):
            cursor[int(last)] = value
        else:
            cursor[last] = value
    return doc


class OpenApiAdapter(BaseAdapter):
    """OpenAPI 3.x 스펙의 description/summary/title만 번역하는 어댑터.

    구조적 필드(type, format, $ref, enum, parameter/schema 이름 등)는 절대 번역하지
    않는다. 실제 LLM 호출·글로서리·ICU 검증·QA는 기존 JsonAdapter와 동일하게
    translate.run_pipeline(govail 게이트웨이)에 위임한다 — 새 LLM 경로를 만들지 않는다.
    """

    def _cache_path(self, source_path: Path, output_dir: Path, lang_code: str) -> Path:
        return output_dir / f"{source_path.stem}.{lang_code}.i18n.json"

    def _output_path(self, source_path: Path, output_dir: Path, lang_code: str) -> Path:
        return output_dir / f"{source_path.stem}.{lang_code}{source_path.suffix}"

    def _flat_nested_content(self, flat: Dict[PathKey, str]) -> str:
        nested = translate._nested_from_leaves(flat)
        return json.dumps(nested, ensure_ascii=False)

    def _resolve_base_flat_from_git(self, source_path: Path) -> Optional[str]:
        try:
            cmd = ["git", "show", f"HEAD:{source_path}"]
            res = subprocess.run(cmd, capture_output=True, text=True, check=True)
            base_doc = json.loads(res.stdout)
        except Exception as e:
            logger.warning(f"Git HEAD에서 이전 OpenAPI 원본을 가져오지 못했습니다: {e}")
            return None
        base_flat = _extract_translatable(base_doc)
        return self._flat_nested_content(base_flat)

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
            source_doc = translate._load_json(source_path, required=True)
        except Exception as e:
            logger.error(f"OpenAPI JSON 파싱 실패 ({source_path}): {e}")
            return 3

        if not is_openapi_document(source_path):
            logger.error(f"OpenAPI 3.x 문서가 아닙니다(openapi/paths 필드 없음): {source_path}")
            return 3

        source_flat = _extract_translatable(source_doc)
        source_flat_content = self._flat_nested_content(source_flat)

        base_flat_content = None
        if base_source_path and base_source_path.exists():
            base_doc = translate._load_json(base_source_path)
            base_flat_content = self._flat_nested_content(_extract_translatable(base_doc))
        elif use_git_diff:
            base_flat_content = self._resolve_base_flat_from_git(source_path)

        glossary = JsonAdapter(self.config)._convert_profile_to_glossary()
        out_dir = output_dir or source_path.parent

        results: List[translate.TranslationResult] = []
        merged_docs: Dict[str, Any] = {}

        for lang in target_langs:
            lang_code = lang.split("-")[0]
            cache_file = self._cache_path(source_path, out_dir, lang_code)
            existing_flat_content = "{}"
            if cache_file.exists():
                try:
                    existing_flat_content = json.dumps(
                        json.loads(cache_file.read_text(encoding="utf-8")),
                        ensure_ascii=False,
                    )
                except Exception:
                    pass

            logger.info(f"[{lang}] OpenAPI 번역 파이프라인 가동 (원본: {source_path.name})...")
            result = translate.run_pipeline(
                source_content=source_flat_content,
                target_lang=lang,
                existing_content=existing_flat_content,
                base_source_content=base_flat_content,
                glossary=glossary,
                sync_all=sync_all,
            )
            results.append(result)
            logger.info(
                f"[{lang}] 완료: selected={len(result.scope.selected)}, "
                f"preserved={len(result.scope.preserved)}, QA={result.qa_status}, score={result.qa_score}"
            )

            if result.success:
                translated_nested = json.loads(result.content)
                translated_flat = translate._leaf_map(translated_nested)
                merged_docs[lang] = translated_flat

        actual_report_path = report_path or Path("lingo-report.json")
        try:
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
            for lang, translated_flat in merged_docs.items():
                lang_code = lang.split("-")[0]
                full_doc = _apply_translations(source_doc, translated_flat)

                output_file = self._output_path(source_path, out_dir, lang_code)
                output_file.write_text(
                    json.dumps(full_doc, ensure_ascii=False, indent=2) + "\n",
                    encoding="utf-8",
                )

                cache_file = self._cache_path(source_path, out_dir, lang_code)
                cache_file.write_text(
                    json.dumps(
                        translate._nested_from_leaves(translated_flat),
                        ensure_ascii=False,
                        indent=2,
                    )
                    + "\n",
                    encoding="utf-8",
                )
                logger.info(f"[{lang}] 번역된 OpenAPI 스펙 저장 완료: {output_file}")

        logger.info("모든 OpenAPI 번역 및 품질 검증 통과!")
        return 0
