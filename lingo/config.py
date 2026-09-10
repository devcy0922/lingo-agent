from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml

from lingo.glossary import NamespacedGlossaryManager
from lingo.types import ProfileConfig


@dataclass
class LingoConfig:
    gateway_url: str = ""
    api_key: str = ""
    translation_model: str = "govail/thinker"
    review_model: str = "govail/thinker"
    timeout: float = 240.0
    min_interval: float = 0.0
    target_langs: List[str] = field(default_factory=lambda: ["en-US", "ja-JP"])
    profile_name: str = "global"
    profile: Optional[ProfileConfig] = None
    glossary_manager: Optional[NamespacedGlossaryManager] = None
    tm_path: Optional[Path] = None
    dry_run: bool = False

    @property
    def namespace(self) -> str:
        return self.profile.name if self.profile else self.profile_name


def load_config(
    config_path: Optional[Path] = None,
    profile_override: Optional[str] = None,
    langs_override: Optional[List[str]] = None,
    dry_run: bool = False,
) -> LingoConfig:
    """환경변수, 설정 파일(.lingo.yml), 프로필을 결합하여 LingoConfig를 생성합니다."""
    # 1. 환경변수 기본값
    env_gateway = os.environ.get("LLM_GATEWAY_URL", "").rstrip("/")
    env_key = os.environ.get("LLM_API_KEY", "")
    legacy_model = os.environ.get("LLM_MODEL", "govail/thinker")
    env_trans_model = os.environ.get("LLM_TRANSLATION_MODEL", legacy_model)
    env_review_model = os.environ.get("LLM_REVIEW_MODEL", legacy_model)
    env_timeout = float(os.environ.get("LLM_TIMEOUT_SECONDS", "240"))
    env_interval = float(os.environ.get("LLM_MIN_REQUEST_INTERVAL_SECONDS", "0"))

    # 2. .lingo.yml 탐색
    file_data: Dict[str, Any] = {}
    resolved_config_path: Optional[Path] = None

    if config_path and config_path.exists():
        resolved_config_path = config_path
    else:
        # CWD에서 탐색
        cwd = Path.cwd()
        for candidate in [cwd / ".lingo.yml", cwd / ".lingo.yaml"]:
            if candidate.exists():
                resolved_config_path = candidate
                break

    if resolved_config_path:
        try:
            with open(resolved_config_path, "r", encoding="utf-8") as f:
                file_data = yaml.safe_load(f) or {}
        except Exception:
            pass

    # 3. 프로필 결정
    profile_name = profile_override or file_data.get("profile") or "global"
    target_langs = langs_override or file_data.get("target_langs") or ["en-US", "ja-JP"]

    # 4. Glossary Manager 및 프로필 병합
    glossary_mgr = NamespacedGlossaryManager()
    
    # 설정 파일 자체가 인라인으로 terms/tone을 정의한 경우 임시 로드하여 병합
    if resolved_config_path and ("terms" in file_data or "tone" in file_data):
        file_profile = glossary_mgr.load_profile_from_file(resolved_config_path)
        if not file_profile.parent:
            file_profile.parent = profile_name
        resolved_profile = glossary_mgr.resolve_profile(file_profile.name)
    else:
        resolved_profile = glossary_mgr.resolve_profile(profile_name)

    # 5. TM 설정
    tm_path = None
    tm_conf = file_data.get("tm", {})
    if isinstance(tm_conf, dict) and tm_conf.get("enabled", True):
        p = tm_conf.get("path")
        if p:
            tm_path = Path(p)
            glossary_mgr.load_tm(tm_path)

    return LingoConfig(
        gateway_url=env_gateway,
        api_key=env_key,
        translation_model=env_trans_model,
        review_model=env_review_model,
        timeout=env_timeout,
        min_interval=env_interval,
        target_langs=target_langs,
        profile_name=profile_name,
        profile=resolved_profile,
        glossary_manager=glossary_mgr,
        tm_path=tm_path,
        dry_run=dry_run,
    )
