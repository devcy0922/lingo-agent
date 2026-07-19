import datetime
from sqlalchemy import Column, String, DateTime, Text, Integer, ForeignKey, JSON, Boolean
from sqlalchemy.orm import relationship
from .database import Base

class Job(Base):
    __tablename__ = "jobs"

    id = Column(String, primary_key=True, index=True)  # UUID 형식
    # 상태 정의:
    #   PENDING       — 작업 생성됨, 아직 처리 전
    #   TRANSLATING   — 에이전트 번역 및 검증 진행 중
    #   REVIEW_READY  — 모든 언어 lint=PASSED, qa_score>=85, is_fallback=False 달성
    #   DEGRADED      — QA API 불가 상태(일부 번역 존재), 수동 검토 필요
    #   QA_FAILED     — 3회 재시도 후 품질 점수 미달
    #   FAILED        — 3회 재시도 후 린트 실패
    #   APPROVED      — 최종 승인 및 파일 배포 완료
    status = Column(String, default="PENDING")
    source_lang = Column(String, default="ko-KR")
    target_langs = Column(JSON, nullable=False)      # ["en-US", "ja-JP"] 등의 리스트
    source_content = Column(Text, nullable=False)    # 업로드된 ko-KR.json 내용 원본

    # 감사(Audit) 필드 — 승인 시 기록
    approved_by = Column(String, nullable=True)      # 승인자 이름/식별자
    approval_notes = Column(Text, nullable=True)     # 승인 메모
    llm_model_used = Column(String, nullable=True)   # 실제 사용된 LLM 모델명

    created_at = Column(DateTime, default=datetime.datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.datetime.utcnow, onupdate=datetime.datetime.utcnow)

    # translations 관계 설정 (cascade로 job 삭제 시 같이 제거되도록 설정)
    translations = relationship("Translation", back_populates="job", cascade="all, delete-orphan")


class Translation(Base):
    __tablename__ = "translations"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    job_id = Column(String, ForeignKey("jobs.id"), nullable=False)
    target_lang = Column(String, nullable=False)          # en-US, ja-JP 등
    translated_content = Column(Text, nullable=True)      # 번역된 JSON 결과물

    # 린트 상태: PENDING / PASSED / FAILED
    lint_status = Column(String, default="PENDING")

    # QA 상태: PENDING / PASSED / FAILED / UNAVAILABLE
    #   UNAVAILABLE — QA API 자체가 응답 불가였음 (LLM 장애)
    qa_status = Column(String, default="PENDING")

    # LLM-as-a-Judge 품질 평가 점수 (0-100, -1=QA 불가)
    quality_score = Column(Integer, default=0)

    # Fallback 번역 여부: True이면 LLM 장애로 로컬 규칙 번역 사용됨
    # is_fallback=True 인 번역은 승인 게이트를 통과할 수 없음
    is_fallback = Column(Boolean, default=False)

    feedback_log = Column(JSON, default=list)  # 검증 과정의 에러 및 피드백 로그 리스트
    attempts = Column(Integer, default=0)       # 재시도 횟수

    job = relationship("Job", back_populates="translations")
