export interface Translation {
  id: number;
  job_id: string;
  target_lang: string;
  translated_content: string | null;
  lint_status: string;
  quality_score: number;
  feedback_log: string[];
  attempts: number;
}

export interface Job {
  id: string;
  status: string;
  source_lang: string;
  target_langs: string[];
  source_content: string;
  created_at: string;
  updated_at: string;
  translations: Translation[];
}

// Vite 개발서버(5173)인 경우 백엔드 포트(9095)로 호스트 강제 변경
const API_BASE = window.location.port === "5173" 
  ? "http://localhost:9095/api" 
  : "/api";

export async function getJobs(): Promise<Job[]> {
  const res = await fetch(`${API_BASE}/jobs`);
  if (!res.ok) throw new Error("잡 목록 조회 실패");
  return res.json();
}

export async function getJobDetail(jobId: string): Promise<Job> {
  const res = await fetch(`${API_BASE}/jobs/${jobId}`);
  if (!res.ok) throw new Error("잡 상세 정보 조회 실패");
  return res.json();
}

export async function createJob(sourceContent: string, targetLangs: string[]): Promise<Job> {
  const res = await fetch(`${API_BASE}/jobs`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ source_content: sourceContent, target_langs: targetLangs }),
  });
  if (!res.ok) throw new Error("번역 잡 생성 실패");
  return res.json();
}

export async function approveJob(jobId: string, notes?: string): Promise<Job> {
  const res = await fetch(`${API_BASE}/jobs/${jobId}/approve`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ notes }),
  });
  if (!res.ok) throw new Error("번역 승인 처리 실패");
  return res.json();
}

export async function deleteJob(jobId: string): Promise<void> {
  const res = await fetch(`${API_BASE}/jobs/${jobId}`, {
    method: "DELETE",
  });
  if (!res.ok) throw new Error("잡 삭제 실패");
}
