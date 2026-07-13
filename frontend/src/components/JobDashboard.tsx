import React from "react";
import { type Job } from "../api";

interface JobDashboardProps {
  jobs: Job[];
  selectedJobId: string | null;
  onSelectJob: (jobId: string) => void;
}

export const JobDashboard: React.FC<JobDashboardProps> = ({ jobs, selectedJobId, onSelectJob }) => {
  const getStatusBadgeClass = (status: string) => {
    switch (status.toUpperCase()) {
      case "PENDING": return "badge-pending";
      case "TRANSLATING": return "badge-translating";
      case "VALIDATING": return "badge-validating";
      case "REVIEW_READY": return "badge-review_ready";
      case "APPROVED": return "badge-approved";
      case "FAILED": return "badge-failed";
      default: return "badge-pending";
    }
  };

  const getStatusLabel = (status: string) => {
    switch (status.toUpperCase()) {
      case "PENDING": return "대기 중";
      case "TRANSLATING": return "번역 중 🤖";
      case "VALIDATING": return "품질 검증 중 🔍";
      case "REVIEW_READY": return "검토 대기";
      case "APPROVED": return "승인 완료 (배포)";
      case "FAILED": return "번역 실패 ❌";
      default: return status;
    }
  };

  return (
    <div className="card" style={{ maxHeight: "550px", overflowY: "auto" }}>
      <h2>2. 번역 작업 모니터링</h2>
      <div style={{ marginTop: "1rem" }}>
        {jobs.length === 0 ? (
          <div style={{ color: "var(--text-muted)", fontSize: "0.9rem", textAlign: "center", padding: "2rem 0" }}>
            등록된 번역 작업이 없습니다.
          </div>
        ) : (
          jobs.map((job) => (
            <div
              key={job.id}
              className={`job-item ${selectedJobId === job.id ? "active" : ""}`}
              onClick={() => onSelectJob(job.id)}
            >
              <div className="job-item-header">
                <span className="job-id">ID: {job.id.substring(0, 8)}...</span>
                <span className={`badge ${getStatusBadgeClass(job.status)}`}>
                  {getStatusLabel(job.status)}
                </span>
              </div>
              <div style={{ display: "flex", justifyContent: "space-between", fontSize: "0.8rem", color: "var(--text-muted)", marginTop: "0.4rem" }}>
                <span>타깃: {job.target_langs.join(", ")}</span>
                <span>{new Date(job.created_at).toLocaleTimeString()}</span>
              </div>
            </div>
          ))
        )}
      </div>
    </div>
  );
};
