# LingoAgent 에이전트 지침

## 1. 실행 경계

- `lingo/`와 `translate.py`는 소비 저장소의 CI 번역 게이트 및 CLI 실행 경로다.
- `backend/`와 `frontend/`는 작업 생성·검토를 위한 웹 데모 경로다. Docker 컨테이너가 healthy여도 CLI 패키지 또는 소비 저장소의 locale 배포가 검증된 것으로 간주하지 않는다.
- fallback, QA 장애, lint 실패, 재시도 한도 초과는 성공으로 우회하지 않는다. 웹 데모의 fallback 결과는 승인 게이트를 통과할 수 없다.

## 2. 런타임 오케스트레이션

- 검증된 Provider 호출 경계는 `소비자 코드 → RuntimeRegistry.get_provider(name) → BaseRuntimeProvider.execute(task) → 선택된 런타임`이다.
- 소비자 코드는 engine-process의 `/v1/process/*`를 직접 호출하지 않는다. `EngineProcessRuntimeProvider`가 Provider 내부에서 해당 HTTP/CLI 어댑터를 소유하며 upstream으로 직접 요청한다.
- **현재 `lingo` CLI는 이 Provider 경로에 아직 연결되지 않았다.** CLI의 `--runtime`은 환경변수만 설정하고 JSON/Markdown 어댑터는 `translate.run_pipeline()`을 호출한다. CLI Provider 통합 전에는 CLI 실행을 Provider 실행으로 보고하지 않는다.
- LangGraph, engine-process, Mock 또는 사용자 정의 Provider는 `BaseRuntimeProvider` 계약 뒤에서 교체할 수 있다. Provider 구현은 지연 import하며 특정 런타임을 필수 의존성으로 전제하지 않는다. Provider 직접 호출/단위 테스트와 실제 CLI·웹 데모 경로를 구분한다.
- MCP 도구는 런타임 공급자와 분리하고, `ArticleBlock[]` 구조·ICU 변수·HTML 태그·용어집 제약을 보존한다.
- 실제 번역·QA·벤치마크 결과와 단위 테스트·Mock 결과를 구분해 보고한다. Newsroom 저장소의 컨테이너 배포만으로 Lingo CLI의 실행 증거를 만들지 않는다.

## 3. 보안 및 데이터

- API 키, 토큰, 개인정보를 코드·문서·로그에 기록하지 않는다. `.env`는 커밋하지 않는다.
- 승인·artifact 출력·소비 저장소 반영은 명시적 게이트와 외부 readback이 있을 때만 성공으로 보고한다.
- 인증·인가가 없는 웹 데모 API를 production approval endpoint로 취급하지 않는다.

## 4. 릴리즈·배포 검증

- 변경 후 `python3 -m pytest -q`, `python3 -m compileall -q lingo tests`, `docker compose config --quiet`를 실행한다.
- Docker 배포 시 `LINGO_VERSION`과 `LINGO_GIT_SHA`를 build arg로 주입하고, Compose 상태·로그·`/healthz`의 서비스/버전/SHA를 각각 확인한다.
- 외부 SSO 경로가 401/302를 반환하면 우회하지 않고, 컨테이너 내부 health readback과 외부 인증 경로를 별도 결과로 기록한다.
- 배포 후 소스 테스트, 이미지 생성, 컨테이너 상태, 실제 HTTP readback, Git tag/remote 상태를 한 주장으로 합치지 않는다.
