from __future__ import annotations

import uuid
from typing import Any, Dict, List, Optional

from lingo.runtimes.base import TranslationTask


class NewsroomArticleAdapter:
    """Newsroom 기사 구조(ArticleBlock[])와 Lingo 다국어 파이프라인 간의 양방향 변환 어댑터."""

    @staticmethod
    def to_task(
        article_data: Dict[str, Any],
        target_lang: str = "en",
        profile_name: str = "default",
        task_id: Optional[str] = None,
    ) -> TranslationTask:
        """뉴스룸 기사 딕셔너리를 표준 TranslationTask로 변환합니다."""
        t_id = task_id or f"art_{article_data.get('id', str(uuid.uuid4())[:8])}_{target_lang}"
        return TranslationTask(
            task_id=t_id,
            source_lang="ko",
            target_lang=target_lang,
            content_type="article_blocks",
            payload=article_data,
            metadata={
                "article_id": article_data.get("id"),
                "desk_id": article_data.get("desk_id"),
                "slug": article_data.get("slug"),
                "profile_name": profile_name,
            },
        )

    @staticmethod
    def format_translated_article(
        original: Dict[str, Any],
        translated_payload: Dict[str, Any],
        target_lang: str,
    ) -> Dict[str, Any]:
        """번역된 페이로드를 뉴스룸 발행 및 다국어 뷰어용 기사 객체로 포맷팅합니다."""
        result = dict(original)
        result["lang"] = target_lang
        result["parent_article_id"] = original.get("id")
        result["slug"] = f"{target_lang}-{original.get('slug', '')}"
        result["headline"] = translated_payload.get("headline", original.get("headline", ""))
        result["dek"] = translated_payload.get("dek", original.get("dek", ""))
        result["body"] = translated_payload.get("body", original.get("body", []))

        # 메타데이터 및 다국어 태그
        tags = list(original.get("tags", []))
        tags.append(f"lang:{target_lang}")
        result["tags"] = tags

        return result
