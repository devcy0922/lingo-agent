import json
import pytest
from pathlib import Path
from lingo.glossary import NamespacedGlossaryManager
from lingo.types import ProfileConfig, GlossaryTerm, ToneConfig


def test_profile_inheritance(tmp_path):
    mgr = NamespacedGlossaryManager(profiles_dir=tmp_path)

    # 1. Global 부모 프로필
    global_file = tmp_path / "global.yml"
    global_file.write_text("""
version: "1"
name: "global"
tone:
  style: "general"
  formality: "polite"
  guidelines:
    - "전사 공통 원칙"
terms:
  - term: "LingoAgent"
    translations:
      en-US: "LingoAgent"
    forbidden: ["링고"]
prohibited_phrases:
  - "클릭하세요"
""", encoding="utf-8")

    # 2. Tech Blog 자식 프로필
    blog_file = tmp_path / "tech_blog.yml"
    blog_file.write_text("""
version: "1"
name: "tech_blog"
inherit: "global"
tone:
  style: "friendly_technical"
  guidelines:
    - "블로그 친절 경어체"
terms:
  - term: "포스트"
    translations:
      en-US: "Post"
""", encoding="utf-8")

    # 3. Admin 자식 프로필 (동일한 '포스트'를 다르게 번역)
    admin_file = tmp_path / "internal_admin.yml"
    admin_file.write_text("""
version: "1"
name: "internal_admin"
inherit: "global"
tone:
  style: "concise_direct"
  formality: "direct"
terms:
  - term: "포스트"
    translations:
      en-US: "Article Item"
""", encoding="utf-8")

    # 프로필 로드
    mgr._load_built_in_profiles()

    resolved_blog = mgr.resolve_profile("tech_blog")
    resolved_admin = mgr.resolve_profile("internal_admin")

    # 상속 확인: 부모의 LingoAgent가 두 자식 모두에 존재
    assert "LingoAgent" in resolved_blog.terms
    assert "LingoAgent" in resolved_admin.terms
    assert "클릭하세요" in resolved_blog.prohibited_phrases

    # 오버라이드 및 충돌 방지 확인: '포스트' 번역이 블로그와 어드민에서 다름
    assert resolved_blog.terms["포스트"].translations["en-US"] == "Post"
    assert resolved_admin.terms["포스트"].translations["en-US"] == "Article Item"

    # 톤 지침 병합 확인
    assert "전사 공통 원칙" in resolved_blog.tone.guidelines
    assert "블로그 친절 경어체" in resolved_blog.tone.guidelines


def test_tm_namespace_isolation(tmp_path):
    mgr = NamespacedGlossaryManager(profiles_dir=tmp_path)
    tm_file = tmp_path / "tm.json"

    # 동일한 한국어 문장을 다른 네임스페이스로 기록
    mgr.record_tm("포스트를 확인하세요.", "en-US", "tech_blog", "Please check out the post.")
    mgr.record_tm("포스트를 확인하세요.", "en-US", "internal_admin", "Review article entry.")

    # 저장 및 새 매니저에서 재로드
    mgr.save_tm(tm_file)

    new_mgr = NamespacedGlossaryManager(profiles_dir=tmp_path)
    new_mgr.load_tm(tm_file)

    # 네임스페이스별 격리 조회 확인
    blog_tm = new_mgr.lookup_tm("포스트를 확인하세요.", "en-US", "tech_blog")
    admin_tm = new_mgr.lookup_tm("포스트를 확인하세요.", "en-US", "internal_admin")
    unknown_tm = new_mgr.lookup_tm("포스트를 확인하세요.", "en-US", "other_ns")

    assert blog_tm == "Please check out the post."
    assert admin_tm == "Review article entry."
    assert unknown_tm is None
