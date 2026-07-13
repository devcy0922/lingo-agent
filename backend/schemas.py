from pydantic import BaseModel, Field
from typing import List, Optional, Any
from datetime import datetime

class TranslationBase(BaseModel):
    target_lang: str
    translated_content: Optional[str] = None
    lint_status: str
    quality_score: int
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
    created_at: datetime
    updated_at: datetime
    translations: List[TranslationResponse] = []

    class Config:
        from_attributes = True

class JobApprove(BaseModel):
    notes: Optional[str] = Field(None, description="리뷰 승인 시 남길 메모")
