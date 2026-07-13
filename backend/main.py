import os
import uuid
import json
from fastapi import FastAPI, Depends, HTTPException, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session
from typing import List

from .config import settings
from .database import engine, Base, get_db
from .models import Job, Translation
from .schemas import JobCreate, JobResponse, JobApprove
from .agent import run_lingo_agent_loop

# DB 테이블 생성
Base.metadata.create_all(bind=engine)

app = FastAPI(
    title="LingoAgent API",
    description="Agentic i18n Translation & Validation Pipeline Gateway",
    version="1.0.0"
)

# CORS 설정 (프론트엔드 Vite 개발 서버 포트 등 허용)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# -----------------
# API 엔드포인트
# -----------------

@app.post("/api/jobs", response_model=JobResponse)
def create_job(payload: JobCreate, background_tasks: BackgroundTasks, db: Session = Depends(get_db)):
    # 1. 입력된 source_content가 유효한 JSON인지 1차 검증
    try:
        json.loads(payload.source_content)
    except json.JSONDecodeError as e:
        raise HTTPException(status_code=400, detail=f"Invalid JSON source: {str(e)}")

    job_id = str(uuid.uuid4())
    
    new_job = Job(
        id=job_id,
        status="PENDING",
        source_lang="ko-KR",
        target_langs=payload.target_langs,
        source_content=payload.source_content
    )
    
    db.add(new_job)
    db.commit()
    db.refresh(new_job)

    # 2. 백그라운드 태스크로 에이전트 루프 작동
    background_tasks.add_task(run_lingo_agent_loop, job_id, db)

    return new_job


@app.get("/api/jobs", response_model=List[JobResponse])
def get_jobs(db: Session = Depends(get_db)):
    return db.query(Job).order_by(Job.created_at.desc()).all()


@app.get("/api/jobs/{job_id}", response_model=JobResponse)
def get_job_detail(job_id: str, db: Session = Depends(get_db)):
    job = db.query(Job).filter(Job.id == job_id).first()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return job


@app.post("/api/jobs/{job_id}/approve", response_model=JobResponse)
def approve_job(job_id: str, payload: JobApprove, db: Session = Depends(get_db)):
    job = db.query(Job).filter(Job.id == job_id).first()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    if job.status != "REVIEW_READY" and job.status != "APPROVED":
        raise HTTPException(status_code=400, detail=f"Cannot approve job in '{job.status}' state.")

    # 번역 데이터 파일로 쓰기 (SQLite -> 로컬 스토리지 Artifact 방출)
    try:
        os.makedirs(settings.OUTPUT_DIR, exist_ok=True)
        # ko-KR 원본 쓰기
        with open(os.path.join(settings.OUTPUT_DIR, "ko-KR.json"), "w", encoding="utf-8") as f:
            f.write(job.source_content)

        # 타깃 언어 번역본 쓰기
        for trans in job.translations:
            if trans.lint_status == "PASSED" and trans.translated_content:
                filename = f"{trans.target_lang}.json"
                filepath = os.path.join(settings.OUTPUT_DIR, filename)
                # 예쁘게 들여쓰기해서 저장
                parsed_json = json.loads(trans.translated_content)
                with open(filepath, "w", encoding="utf-8") as f:
                    json.dump(parsed_json, f, ensure_ascii=False, indent=2)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to output translation files: {str(e)}")

    job.status = "APPROVED"
    db.commit()
    db.refresh(job)
    return job


@app.delete("/api/jobs/{job_id}")
def delete_job(job_id: str, db: Session = Depends(get_db)):
    job = db.query(Job).filter(Job.id == job_id).first()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    
    db.delete(job)
    db.commit()
    return {"detail": "Job successfully deleted"}

# -----------------
# React SPA 정적 서빙 및 Catch-all Fallback
# -----------------

frontend_dist_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "frontend/dist")

if os.path.exists(frontend_dist_path):
    app.mount("/assets", StaticFiles(directory=os.path.join(frontend_dist_path, "assets")), name="assets")

    @app.get("/{fallback_path:path}")
    def spa_fallback(fallback_path: str):
        # API 라우팅을 침범하지 않도록 예외 처리
        if fallback_path.startswith("api/"):
            raise HTTPException(status_code=404, detail="API route not found")
        
        index_file = os.path.join(frontend_dist_path, "index.html")
        if os.path.exists(index_file):
            return FileResponse(index_file)
        raise HTTPException(status_code=404, detail="SPA index.html not found")
else:
    @app.get("/")
    def index_fallback():
        return {
            "message": "LingoAgent API is running. Frontend build directory not detected yet. Run 'pnpm build:frontend' to serve UI.",
            "api_docs": "/docs"
        }
