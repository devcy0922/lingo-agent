import React, { useState } from "react";
import { type Job, approveJob, deleteJob } from "../api";
import { DiffViewer } from "./DiffViewer";

interface ApprovalConsoleProps {
  job: Job;
  onActionComplete: () => void;
}

export const ApprovalConsole: React.FC<ApprovalConsoleProps> = ({ job, onActionComplete }) => {
  const [activeLang, setActiveLang] = useState<string>(job.target_langs[0] || "");
  const [approving, setApproving] = useState(false);
  const [deleting, setDeleting] = useState(false);

  const activeTranslation = job.translations.find((t) => t.target_lang === activeLang);

  const handleApprove = async () => {
    if (!window.confirm("번역을 승인하시겠습니까? 로컬 디렉토리에 다국어 리소스 파일이 생성됩니다.")) return;
    setApproving(true);
    try {
      await approveJob(job.id);
      alert("번역 승인 완료! 로컬 data/output/ 경로에 번역 리소스 파일들이 배포되었습니다.");
      onActionComplete();
    } catch (err: any) {
      alert("승인 오류: " + err.message);
    } finally {
      setApproving(false);
    }
  };

  const handleDelete = async () => {
    if (!window.confirm("이 작업을 완전히 삭제하시겠습니까?")) return;
    setDeleting(true);
    try {
      await deleteJob(job.id);
      onActionComplete();
    } catch (err: any) {
      alert("삭제 오류: " + err.message);
    } finally {
      setDeleting(false);
    }
  };

  // 점수에 따른 테마 컬러 산정
  const getScoreColor = (score: number) => {
    if (score >= 90) return "var(--success)";
    if (score >= 80) return "var(--warning)";
    return "var(--error)";
  };

  return (
    <div className="card">
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "1.5rem" }}>
        <h2>3. 에이전트 번역 품질 및 결과 검토</h2>
        <div style={{ display: "flex", gap: "0.5rem" }}>
          <button
            onClick={handleDelete}
            className="btn btn-secondary"
            style={{ width: "auto", padding: "0.5rem 1rem", borderColor: "var(--error)", color: "var(--error)" }}
            disabled={deleting}
          >
            {deleting ? "삭제 중..." : "작업 삭제"}
          </button>
          
          {(job.status === "REVIEW_READY" || job.status === "APPROVED") && (
            <button
              onClick={handleApprove}
              className="btn btn-primary"
              style={{ width: "auto", padding: "0.5rem 1.5rem", background: job.status === "APPROVED" ? "var(--border)" : "var(--primary)" }}
              disabled={approving || job.status === "APPROVED"}
            >
              {approving ? "배포 중..." : job.status === "APPROVED" ? "배포 및 승인 완료 ✓" : "최종 승인 및 로컬 배포 🚀"}
            </button>
          )}
        </div>
      </div>

      {/* 타깃 언어 탭 */}
      <div className="tab-menu">
        {job.target_langs.map((lang) => (
          <button
            key={lang}
            className={`tab-btn ${activeLang === lang ? "active" : ""}`}
            onClick={() => setActiveLang(lang)}
          >
            {lang}
          </button>
        ))}
      </div>

      {activeTranslation ? (
        <div style={{ marginTop: "1.5rem" }}>
          {/* 품질 스코어 카드 */}
          <div
            style={{
              display: "grid",
              gridTemplateColumns: "150px 1fr",
              gap: "1.5rem",
              background: "var(--bg-surface-elevated)",
              padding: "1rem",
              borderRadius: "8px",
              border: "1px solid var(--border)",
              alignItems: "center"
            }}
          >
            <div style={{ textAlign: "center", borderRight: "1px solid var(--border)" }}>
              <div style={{ fontSize: "0.8rem", color: "var(--text-muted)", marginBottom: "0.2rem" }}>LLM Quality Score</div>
              <div style={{ fontSize: "2rem", fontWeight: "bold", color: getScoreColor(activeTranslation.quality_score) }}>
                {activeTranslation.quality_score}점
              </div>
            </div>
            <div>
              <div style={{ fontSize: "0.85rem", fontWeight: "bold", marginBottom: "0.3rem" }}>검증 리포트 & 피드백 로그</div>
              <div style={{ fontSize: "0.8rem", color: "var(--text-muted)" }}>
                상태: <span style={{ color: activeTranslation.lint_status === "PASSED" ? "var(--success)" : "var(--error)" }}>
                  {activeTranslation.lint_status}
                </span>
                {" | "} 시도 횟수: {activeTranslation.attempts}/3회
              </div>
            </div>
          </div>

          {/* 에이전트 Thought Process 타임라인 */}
          <div style={{ marginTop: "1.5rem" }}>
            <h3 style={{ fontSize: "0.95rem", color: "var(--text-muted)", marginBottom: "0.5rem" }}>🤖 Agent Thought Timeline (사고 히스토리)</h3>
            <div className="thought-timeline">
              {activeTranslation.feedback_log && activeTranslation.feedback_log.map((log, index) => (
                <div key={index} className="thought-step">
                  <div className="thought-header">
                    <span>STEP {index + 1}</span>
                    <span>상태: {log.includes("Lint") ? "Linter Check" : "QA Review"}</span>
                  </div>
                  <div className="thought-msg">{log}</div>
                </div>
              ))}
            </div>
          </div>

          {/* Diff 뷰어 */}
          <div style={{ marginTop: "2rem" }}>
            <h3 style={{ fontSize: "0.95rem", color: "var(--text-muted)", marginBottom: "0.5rem" }}>📝 Translation Diff</h3>
            <DiffViewer
              sourceContent={job.source_content}
              translatedContent={activeTranslation.translated_content}
            />
          </div>
        </div>
      ) : (
        <div style={{ color: "var(--text-muted)", padding: "3rem", textAlign: "center" }}>
          해당 언어의 번역 결과물이 아직 생성되지 않았습니다.
        </div>
      )}
    </div>
  );
};
