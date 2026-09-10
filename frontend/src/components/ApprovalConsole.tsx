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
  const canApprove = job.status === "REVIEW_READY";

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
        <div>
          <h2>3. 결과 검토 및 내보내기</h2>
          <p className="card-intro">모든 언어가 검증을 통과해야 승인할 수 있습니다.</p>
        </div>
        <div style={{ display: "flex", gap: "0.5rem" }}>
          <button
            onClick={handleDelete}
            className="btn btn-secondary"
            style={{ width: "auto", padding: "0.5rem 1rem", borderColor: "var(--error)", color: "var(--error)" }}
            disabled={deleting}
          >
            {deleting ? "삭제 중..." : "작업 삭제"}
          </button>
          
          {(canApprove || job.status === "APPROVED") && (
            <button
              onClick={handleApprove}
              className="btn btn-primary"
              style={{ width: "auto", padding: "0.5rem 1.5rem", background: job.status === "APPROVED" ? "var(--border)" : "var(--primary)" }}
              disabled={approving || job.status === "APPROVED" || !canApprove}
            >
              {approving ? "배포 중..." : job.status === "APPROVED" ? "배포 및 승인 완료 ✓" : "최종 승인 및 로컬 배포 🚀"}
            </button>
          )}
        </div>
      </div>

      <div className={`gate-summary ${canApprove || job.status === "APPROVED" ? "gate-pass" : "gate-blocked"}`}>
        <strong>{job.status === "APPROVED" ? "내보내기 완료" : canApprove ? "승인 가능" : "승인 불가"}</strong>
        <span>
          {job.status === "APPROVED"
            ? "data/output/에 번역 파일이 기록되었습니다."
            : canApprove
              ? "구조 검사와 품질 QA를 모두 통과했습니다."
              : "번역·검증이 끝나거나 모든 품질 조건을 만족할 때까지 승인할 수 없습니다."}
        </span>
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
              <div style={{ fontSize: "0.8rem", color: "var(--text-muted)", marginBottom: "0.2rem" }}>품질 QA 점수</div>
              <div style={{ fontSize: "2rem", fontWeight: "bold", color: getScoreColor(activeTranslation.quality_score) }}>
                {activeTranslation.quality_score >= 0 ? `${activeTranslation.quality_score}점` : "판정 없음"}
              </div>
            </div>
            <div>
              <div style={{ fontSize: "0.85rem", fontWeight: "bold", marginBottom: "0.3rem" }}>검증 결과</div>
              <div style={{ fontSize: "0.8rem", color: "var(--text-muted)" }}>
                구조 검사: <span className={activeTranslation.lint_status === "PASSED" ? "text-success" : "text-error"}>{activeTranslation.lint_status}</span>
                {" · "}품질 QA: <span className={activeTranslation.qa_status === "PASSED" ? "text-success" : "text-error"}>{activeTranslation.qa_status}</span>
                {" · "}시도 {activeTranslation.attempts}/3
              </div>
              {activeTranslation.is_fallback && <div className="inline-warning">LLM 장애로 만든 fallback 결과입니다. 승인할 수 없습니다.</div>}
            </div>
          </div>

          {/* 검증 기록 */}
          <div style={{ marginTop: "1.5rem" }}>
            <h3 style={{ fontSize: "0.95rem", color: "var(--text-muted)", marginBottom: "0.5rem" }}>검증 기록</h3>
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
