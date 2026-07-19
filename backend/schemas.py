from pydantic import BaseModel, Field
from typing import List, Optional, Any
from datetime import datetime


class TranslationBase(BaseModel):
    target_lang: str
    translated_content: Optional[str] = None
    lint_status: str
    qa_status: str = "PENDING"
    quality_score: int
    is_fallback: bool = False
    feedback_log: List[Any] = []
    attempts: int


class TranslationResponse(TranslationBase):
    id: int
    job_id: str

    class Config:
        from_attributes = True


class JobCreate(BaseModel):
    source_content: str = Field(..., description="원본 ko-KR JSON 내용")
    target_langs: List[str] = Field(default=["en-US", "ja-JP"], description="번역 대상 타깃 언어 목록")


class JobResponse(BaseModel):
    id: str
    status: str
    source_lang: str
    target_langs: List[str]
    source_content: str
    # 감사(Audit) 필드
    approved_by: Optional[str] = None
    approval_notes: Optional[str] = None
    llm_model_used: Optional[str] = None
    created_at: datetime
    updated_at: datetime
    translations: List[TranslationResponse] = []

    class Config:
        from_attributes = True


class JobApprove(BaseModel):
    approved_by: Optional[str] = Field(None, description="승인자 이름 또는 식별자")
    notes: Optional[str] = Field(None, description="리뷰 승인 시 남길 메모")


class JobReject(BaseModel):
    reason: Optional[str] = Field(None, description="반려 사유")
