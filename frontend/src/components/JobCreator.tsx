import React, { useState } from "react";
import { createJob } from "../api";

interface JobCreatorProps {
  onJobCreated: (jobId: string) => void;
}

const DEFAULT_SAMPLE = `{
  "dashboard.title": "AI 국제화 오케스트레이터",
  "welcome.user": "{username}님, 다시 만나서 반갑습니다!",
  "task.progress": "현재 작업 진행률은 {percent}%이며, 총 {count}개의 번역이 대기 중입니다.",
  "button.approve": "최종 승인 및 PR 생성"
}`;

export const JobCreator: React.FC<JobCreatorProps> = ({ onJobCreated }) => {
  const [sourceContent, setSourceContent] = useState(DEFAULT_SAMPLE);
  const [targetLangs, setTargetLangs] = useState<string[]>(["en-US", "ja-JP"]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setLoading(true);
    setError(null);
    try {
      // JSON 문법 정적 검증
      JSON.parse(sourceContent);
      
      const newJob = await createJob(sourceContent, targetLangs);
      onJobCreated(newJob.id);
    } catch (err: any) {
      setError(err.message || "올바른 JSON 형식이 아닙니다.");
    } finally {
      setLoading(false);
    }
  };

  const handleLangToggle = (lang: string) => {
    if (targetLangs.includes(lang)) {
      if (targetLangs.length > 1) {
        setTargetLangs(targetLangs.filter(l => l !== lang));
      }
    } else {
      setTargetLangs([...targetLangs, lang]);
    }
  };

  return (
    <div className="card">
      <h2>1. 번역 작업 생성 (ko-KR)</h2>
      <form onSubmit={handleSubmit} style={{ marginTop: "1rem" }}>
        <div className="form-group">
          <label>소스 JSON 데이터 (ko-KR)</label>
          <textarea
            value={sourceContent}
            onChange={(e) => setSourceContent(e.target.value)}
            placeholder="여기에 번역할 한국어 JSON 데이터를 입력하세요..."
          />
        </div>

        <div className="form-group">
          <label>타깃 언어 선택</label>
          <div className="checkbox-group">
            <label className="checkbox-label">
              <input
                type="checkbox"
                checked={targetLangs.includes("en-US")}
                onChange={() => handleLangToggle("en-US")}
              />
              영어 (en-US)
            </label>
            <label className="checkbox-label">
              <input
                type="checkbox"
                checked={targetLangs.includes("ja-JP")}
                onChange={() => handleLangToggle("ja-JP")}
              />
              일본어 (ja-JP)
            </label>
          </div>
        </div>

        {error && <div style={{ color: "var(--error)", fontSize: "0.85rem", marginBottom: "1rem" }}>{error}</div>}

        <button type="submit" className="btn btn-primary" disabled={loading}>
          {loading ? "에이전트 가동 중..." : "번역 에이전트 루프 실행 ⚡"}
        </button>
      </form>
    </div>
  );
};
