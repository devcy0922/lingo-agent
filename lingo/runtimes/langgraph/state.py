from __future__ import annotations

from typing import Any, Dict, List, Optional, TypedDict


class TranslationItem(TypedDict, total=False):
    """단일 번역 세그먼트/블록 단위의 상태."""
    id: str
    path: str
    source_text: str
    target_text: str
    status: str  # 'pending', 'translated', 'lint_failed', 'qa_failed', 'passed'
    lint_errors: List[str]
    qa_score: float
    critique: str
    retry_count: int


class LangGraphState(TypedDict, total=False):
    """LangGraph 상태 머신 전체 공유 상태."""
    task_id: str
    source_lang: str
    target_lang: str
    content_type: str
    raw_payload: Any
    items: List[TranslationItem]
    profile: Optional[Any]
    current_stage: str
    retry_count: int
    max_retries: int
    overall_status: str  # 'RUNNING', 'SUCCESS', 'QA_FAILED', 'ERROR'
    qa_summary: Dict[str, Any]
    output_payload: Any
    events: List[Dict[str, Any]]
    error: Optional[str]
