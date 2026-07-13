import datetime
from sqlalchemy import Column, String, DateTime, Text, Integer, ForeignKey, JSON
from sqlalchemy.orm import relationship
from .database import Base

class Job(Base):
    __tablename__ = "jobs"

    id = Column(String, primary_key=True, index=True) # UUID 형식
    status = Column(String, default="PENDING") # PENDING, TRANSLATING, VALIDATING, RETRYING, REVIEW_READY, APPROVED, FAILED
    source_lang = Column(String, default="ko-KR")
    target_langs = Column(JSON, nullable=False) # ["en-US", "ja-JP"] 등의 리스트
    source_content = Column(Text, nullable=False) # 업로드된 ko-KR.json의 내용 원본
    created_at = Column(DateTime, default=datetime.datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.datetime.utcnow, onupdate=datetime.datetime.utcnow)

    # translations 관계 설정 (cascade로 job 삭제 시 같이 제거되도록 설정)
    translations = relationship("Translation", back_populates="job", cascade="all, delete-orphan")

class Translation(Base):
    __tablename__ = "translations"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    job_id = Column(String, ForeignKey("jobs.id"), nullable=False)
    target_lang = Column(String, nullable=False) # en-US, ja-JP 등
    translated_content = Column(Text, nullable=True) # 번역된 JSON 결과물
    lint_status = Column(String, default="PENDING") # PENDING, PASSED, FAILED
    quality_score = Column(Integer, default=0) # LLM-as-a-Judge 품질 평가 점수
    feedback_log = Column(JSON, default=list) # 검증 과정의 에러 및 피드백 로그 리스트
    attempts = Column(Integer, default=0) # 재시도 횟수

    job = relationship("Job", back_populates="translations")
