from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

import yaml

from lingo.types import GlossaryTerm, ProfileConfig, ToneConfig


class NamespacedGlossaryManager:
    """계층형 네임스페이스 기반 용어집(Glossary) 및 번역 메모리(TM) 관리자.
    
    하드코딩 없이 YAML/JSON 기반 프로필을 로드하며, 상속(Inheritance)을 통해
    전사 공통(global) 규칙 위에 프로젝트별(tech_blog, internal_admin 등) 톤과 용어를 오버라이드합니다.
    """

    def __init__(self, profiles_dir: Optional[Path] = None):
        self.profiles_dir = profiles_dir or (Path(__file__).resolve().parent.parent / "profiles")
        self.profiles: Dict[str, ProfileConfig] = {}
        self._tm_cache: Dict[Tuple[str, str, str], str] = {}  # (namespace, source_text, target_lang) -> translated_text
        self._load_built_in_profiles()

    def _load_built_in_profiles(self) -> None:
        """기본 내장 프로필 디렉토리에서 .yml/.yaml 파일들을 로드합니다."""
        if not self.profiles_dir.exists():
            return
        for file in self.profiles_dir.glob("*.y*ml"):
            try:
                self.load_profile_from_file(file)
            except Exception as e:
                # 로깅 또는 무시
                pass

    def load_profile_from_file(self, path: Path) -> ProfileConfig:
        """YAML 파일로부터 단일 프로필 설정을 로드합니다."""
        with open(path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}

        name = data.get("name") or path.stem
        parent = data.get("parent") or data.get("inherit")
        
        tone_data = data.get("tone", {})
        tone = ToneConfig(
            style=tone_data.get("style", "general"),
            formality=tone_data.get("formality", "polite"),
            guidelines=tone_data.get("guidelines", []),
        )

        terms: Dict[str, GlossaryTerm] = {}
        for raw_term in data.get("terms", []):
            if isinstance(raw_term, dict):
                src = raw_term.get("term", "")
                if src:
                    terms[src] = GlossaryTerm(
                        term=src,
                        translations=raw_term.get("translations", {}),
                        forbidden=raw_term.get("forbidden", []),
                        note=raw_term.get("note", ""),
                    )

        profile = ProfileConfig(
            name=name,
            parent=parent,
            tone=tone,
            terms=terms,
            key_scoped_rules=data.get("key_scoped_rules", {}),
            prohibited_phrases=data.get("prohibited_phrases", []),
        )
        self.profiles[name] = profile
        return profile

    def resolve_profile(self, name_or_path: str) -> ProfileConfig:
        """상속 관계를 해결(Resolve)하여 최종 적용될 병합 프로필을 생성합니다."""
        # 1. 파일 경로인 경우 직접 로드
        path = Path(name_or_path)
        if path.exists() and path.is_file():
            profile = self.load_profile_from_file(path)
            profile_name = profile.name
        else:
            profile_name = name_or_path

        if profile_name not in self.profiles:
            # 프로필이 없으면 기본 빈 프로필 생성
            return ProfileConfig(name=profile_name)

        current = self.profiles[profile_name]
        
        # 부모가 있는 경우 재귀적으로 상속 해결
        if current.parent and current.parent in self.profiles and current.parent != current.name:
            parent_resolved = self.resolve_profile(current.parent)
            
            # 병합: 부모 위에 자식 덮어쓰기
            merged_terms = dict(parent_resolved.terms)
            merged_terms.update(current.terms)

            merged_key_rules = dict(parent_resolved.key_scoped_rules)
            for k, rules in current.key_scoped_rules.items():
                if k in merged_key_rules:
                    merged_key_rules[k] = merged_key_rules[k] + rules
                else:
                    merged_key_rules[k] = rules

            merged_prohibited = list(set(parent_resolved.prohibited_phrases + current.prohibited_phrases))
            merged_guidelines = parent_resolved.tone.guidelines + current.tone.guidelines

            merged_tone = ToneConfig(
                style=current.tone.style or parent_resolved.tone.style,
                formality=current.tone.formality or parent_resolved.tone.formality,
                guidelines=merged_guidelines,
            )

            return ProfileConfig(
                name=current.name,
                parent=current.parent,
                tone=merged_tone,
                terms=merged_terms,
                key_scoped_rules=merged_key_rules,
                prohibited_phrases=merged_prohibited,
            )

        return current

    # ----------------------------------------------------------------------
    # Translation Memory (TM) - 네임스페이스 격리 관리
    # ----------------------------------------------------------------------
    def load_tm(self, tm_file: Path) -> None:
        """TM JSON 파일로부터 과거 번역 메모리를 로드합니다."""
        if not tm_file.exists():
            return
        try:
            with open(tm_file, "r", encoding="utf-8") as f:
                entries = json.load(f)
                for item in entries:
                    ns = item.get("namespace", "default")
                    src = item.get("source", "")
                    lang = item.get("target_lang", "")
                    trans = item.get("translated", "")
                    if src and lang and trans:
                        self._tm_cache[(ns, src, lang)] = trans
        except Exception:
            pass


    def save_tm(self, tm_file: Path) -> None:
        """현재 캐시된 TM 엔트리를 파일로 직렬화합니다."""
        os.makedirs(tm_file.parent, exist_ok=True)
        entries = [
            {
                "namespace": ns,
                "source": src,
                "target_lang": lang,
                "translated": trans,
            }
            for (ns, src, lang), trans in self._tm_cache.items()
        ]
        with open(tm_file, "w", encoding="utf-8") as f:
            json.dump(entries, f, ensure_ascii=False, indent=2)

    def lookup_tm(self, source: str, target_lang: str, namespace: str) -> Optional[str]:
        """네임스페이스와 정확히 일치하는 번역 메모리 캐시를 조회합니다."""
        return self._tm_cache.get((namespace, source.strip(), target_lang))

    def record_tm(self, source: str, target_lang: str, namespace: str, translated: str) -> None:
        """성공적으로 검증 및 승인된 번역문을 네임스페이스와 함께 저장합니다."""
        if source.strip() and translated.strip():
            self._tm_cache[(namespace, source.strip(), target_lang)] = translated.strip()


def load_profile(name_or_path: str = "global") -> ProfileConfig:
    """기본 NamespacedGlossaryManager를 통해 프로필 설정을 로드하고 반환합니다."""
    manager = NamespacedGlossaryManager()
    return manager.resolve_profile(name_or_path)

