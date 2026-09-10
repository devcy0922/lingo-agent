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
          <h1>LingoAgent 번역 배포 게이트</h1>
          <p>한국어 원문에서 번역 후보를 만들고, 검증을 통과한 결과만 내보냅니다.</p>
        </div>
        <div style={{ fontSize: "0.85rem", color: "var(--text-muted)", display: "flex", gap: "1rem" }}>
          <span>로컬 데모</span>
        </div>
      </header>

      <section className="purpose-card">
        <div>
          <strong>이 화면에서 바뀌는 것</strong>
          <p>승인 시 <code>data/output/</code>에 <code>ko-KR.json</code>과 대상 언어 JSON이 생성됩니다.</p>
        </div>
        <div className="workflow-steps" aria-label="번역 처리 단계">
          <span><b>1</b> 원문 입력</span>
          <span className="step-arrow">→</span>
          <span><b>2</b> 번역·검증</span>
          <span className="step-arrow">→</span>
          <span><b>3</b> 승인·내보내기</span>
        </div>
      </section>

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
              <h2 style={{ border: "none", padding: 0 }}>작업을 만들면 여기서 결과를 확인합니다</h2>
              <p style={{ fontSize: "0.9rem", marginTop: "0.5rem", maxWidth: "400px" }}>
                번역 후보, 변수 보존 검사, 품질 판정 결과를 언어별로 확인한 뒤 승인할 수 있습니다.
              </p>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

export default App;
