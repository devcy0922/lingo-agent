import { useState, useEffect, useRef } from "react";
import { type Job, getJobs, getJobDetail } from "./api";
import { JobCreator } from "./components/JobCreator";
import { JobDashboard } from "./components/JobDashboard";
import { ApprovalConsole } from "./components/ApprovalConsole";

function App() {
  const [jobs, setJobs] = useState<Job[]>([]);
  const [selectedJobId, setSelectedJobId] = useState<string | null>(null);
  const pollTimerRef = useRef<any | null>(null);

  const fetchJobs = async () => {
    try {
      const data = await getJobs();
      setJobs(data);
      // 만약 선택된 잡이 있고, 그 잡이 아직 진행 중인 상태라면 실시간 갱신 처리
      if (selectedJobId) {
        const selectedJob = data.find((j) => j.id === selectedJobId);
        if (selectedJob && ["PENDING", "TRANSLATING", "VALIDATING", "RETRYING"].includes(selectedJob.status)) {
          // 상세 최신 정보가 있다면 반영
          const detailed = await getJobDetail(selectedJobId);
          setJobs((prevJobs) => prevJobs.map((j) => (j.id === selectedJobId ? detailed : j)));
        }
      }
    } catch (err) {
      console.error("작업 풀링 중 오류 발생:", err);
    }
  };

  // 초기 로딩
  useEffect(() => {
    fetchJobs();
  }, []);

  // 주기적 폴링 설정 (에이전트 진행 상황을 실시간 반영하기 위함)
  useEffect(() => {
    // 진행 중인 잡이 하나라도 존재하면 2초 주기로 폴링
    const hasActiveJob = jobs.some((j) =>
      ["PENDING", "TRANSLATING", "VALIDATING", "RETRYING"].includes(j.status)
    );

    if (hasActiveJob) {
      if (!pollTimerRef.current) {
        pollTimerRef.current = setInterval(fetchJobs, 2000);
      }
    } else {
      if (pollTimerRef.current) {
        clearInterval(pollTimerRef.current);
        pollTimerRef.current = null;
      }
    }

    return () => {
      if (pollTimerRef.current) {
        clearInterval(pollTimerRef.current);
        pollTimerRef.current = null;
      }
    };
  }, [jobs, selectedJobId]);

  const handleJobCreated = (jobId: string) => {
    setSelectedJobId(jobId);
    fetchJobs();
  };

  const handleActionComplete = () => {
    setSelectedJobId(null);
    fetchJobs();
  };

  const selectedJob = jobs.find((j) => j.id === selectedJobId) || null;

  return (
    <div className="app-container">
      <header>
        <div className="logo-section">
          <h1>LingoAgent</h1>
          <p>Agentic i18n Translation & Validation Pipeline Console</p>
        </div>
        <div style={{ fontSize: "0.85rem", color: "var(--text-muted)", display: "flex", gap: "1rem" }}>
          <span>레포지토리: lingo-agent</span>
          <span>상태: Live ⚡</span>
        </div>
      </header>

      <div className="main-grid">
        {/* 사이드바 영역 */}
        <div style={{ display: "flex", flexDirection: "column", gap: "2rem" }}>
          <JobCreator onJobCreated={handleJobCreated} />
          
          <JobDashboard
            jobs={jobs}
            selectedJobId={selectedJobId}
            onSelectJob={(id) => setSelectedJobId(id)}
          />
        </div>

        {/* 본문 영역 */}
        <div>
          {selectedJob ? (
            <ApprovalConsole
              job={selectedJob}
              onActionComplete={handleActionComplete}
            />
          ) : (
            <div
              className="card"
              style={{
                display: "flex",
                flexDirection: "column",
                alignItems: "center",
                justifyContent: "center",
                minHeight: "450px",
                color: "var(--text-muted)",
                textAlign: "center"
              }}
            >
              <div style={{ fontSize: "3rem", marginBottom: "1rem" }}>🤖</div>
              <h2 style={{ border: "none", padding: 0 }}>번역 작업을 선택하거나 생성하세요</h2>
              <p style={{ fontSize: "0.9rem", marginTop: "0.5rem", maxWidth: "400px" }}>
                에이전트가 한국어 리소스를 읽어 다국어 번역을 자율 수행하고, ICU 포맷 린팅 및 LLM 품질 채점을 실시간 진행합니다.
              </p>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

export default App;
