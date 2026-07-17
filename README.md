# LingoAgent (i18n Localization Agent)

LingoAgent는 개발자가 **한국어(`ko-KR`) UI 리소스 파일만 관리**하면, 자율 AI 에이전트가 타깃 언어 번역, ICU 포맷 린팅, 번역 품질 검증(LLM-as-a-Judge)을 수행하고, 최종 변경사항을 Diff를 통해 시각적으로 확인 및 승인하여 배포할 수 있는 **i18n 국제화 자동화 에이전트 데모 시스템**입니다.

## 🚀 주요 기능
* **자율 번역 및 검증 루프 (LingoAgent Executor)**: LLM 번역 결과에 대한 1차 정적 린팅(Key 매핑 여부 및 ICU 변수명 무결성 검증)과 2차 품질 평가(LLM-as-a-Judge, 85점 합격 컷오프)를 자율적으로 재시도 루프(Max 3회)를 돌며 자체 수정합니다.
* **Thought Timeline (사고 히스토리) 시각화**: 에이전트가 검증에 실패하여 왜 재번역을 시도했는지, 품질 점수를 몇 점을 주었는지 단계별 사고 과정을 프론트엔드 UI 타임라인으로 투명하게 보여줍니다.
* **ICU Message Format 및 변수 무결성 하이라이팅**: 변수 구조(`{username}` 등)가 훼손되지 않았는지 확인하고 UI에서 보기 좋게 시각화해 줍니다.
* **초경량 데모 아키텍처**: 별도의 PostgreSQL, NGINX 설치 없이 SQLite와 FastAPI SPA Catch-all 서빙을 사용하여 **9095 단일 포트**에서 동작합니다.

---

## 🛠️ 사전 요구사항
* Node.js (v18 이상) 및 `pnpm`
* Python (v3.9 이상)

---

## 💻 실행 방법

### 1. 환경변수 설정
이 레포지토리 루트의 `.env.example` 파일을 복사하여 `.env` 파일을 생성합니다.
```bash
cp .env.example .env
```
`.env` 파일을 편집하여 실제 LLM 게이트웨이 주소를 입력합니다.
```ini
LLM_GATEWAY_URL=https://gateway.example.com/v1
LLM_MODEL=meta-llama/Meta-Llama-3-8B-Instruct
```
> **Tip**: 만약 LLM Gateway 통신에 실패하더라도 데모 구동이 끊어지지 않도록, 코드 레벨에서 자동으로 가짜 번역(Simulated Translation)으로 Fallback 처리되어 원활한 시연이 가능합니다.

### 2. 백엔드 의존성 및 Python 가상환경 설정
```bash
# 가상환경 생성 및 활성화
python3 -m venv .venv
source .venv/bin/activate

# 의존성 패키지 설치
pip install -r backend/requirements.txt
```

### 3. 프론트엔드 의존성 설치 및 빌드
```bash
# 루트 디렉토리에서 패키지 설치
pnpm install

# 프론트엔드 빌드 (FastAPI가 SPA 정적 서빙할 수 있도록 build 완료)
pnpm build:frontend
```

### 4. 통합 데모 서버 실행
```bash
# 백엔드 서버 가동 (FastAPI가 9095 포트에서 API와 빌드된 프론트엔드를 동시에 서빙)
pnpm start:backend
```
실행 후 브라우저에서 **`http://localhost:9095`** 에 접속하면 Sleek HSL Dark Mode로 만들어진 LingoAgent 제어반 웹 UI를 볼 수 있습니다.

---

## 🧪 시연 검증 시나리오
1. **번역 작업 생성**: 웹 UI 왼쪽 상단의 에디터에 기본 탑재된 ICU 변수 포함 샘플 JSON(`ko-KR`)을 활용해 `번역 에이전트 루프 실행` 버튼을 누릅니다.
2. **에이전트 진행 모니터링**: 2초마다 백엔드를 풀링하며 `번역 중 🤖` -> `품질 검증 중 🔍` -> `검토 대기`로 변하는 뱃지 상태를 확인합니다.
3. **Thought Timeline 및 Diff 확인**: 검토 대기(Review Ready) 상태인 작업을 클릭하고, 에이전트가 번역을 거치며 판단한 Thought Timeline 로그와 변수가 하이라이팅된 Diff 뷰어를 관찰합니다.
4. **최종 승인 및 배포**: `최종 승인 및 로컬 배포 🚀` 버튼을 클릭합니다.
5. **결과 파일 확인**: 로컬 디렉토리 `data/output/` 경로 아래에 원본 `ko-KR.json`과 번역 완료된 `en-US.json`, `ja-JP.json` 파일들이 예쁜 포맷으로 생성되었는지 확인합니다.
