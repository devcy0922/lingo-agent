# Changelog

## [1.3.0] - 2026-10-12

- `RuntimeRegistry → Provider → Runtime` 경계를 engine-process와 LangGraph에 공통 적용했다.
- concrete Provider를 지연 import하고 LangGraph를 선택적 extra로 분리해 engine-process-only 환경에서도 Registry를 사용할 수 있게 했다.
- 기본 벤치마크가 설치되지 않은 런타임을 전제하지 않도록 현재 환경의 Provider를 기준으로 동작하게 했다.
- `runtime-provider-pattern` 스킬의 환경 중립적 계약과 deprecated `lingo-runtime` 호환 alias를 반영했다.

## [1.2.0] - 2026-10-12

### Added

- LangGraph·engine-process·Mock 런타임 프로바이더와 MCP 도구 계층을 통합한 다국어 오케스트레이션 파이프라인을 릴리즈 기준으로 고정했다.
- `healthz` 응답에 `service`, `version`, `git_sha`를 추가해 컨테이너 기동 상태와 실제 제공 버전을 분리해서 확인할 수 있게 했다.
- CLI, Python 패키지, 웹 데모 API의 릴리즈 버전을 `1.2.0`으로 정렬했다.

### 운영 경계

- Docker 이미지는 `backend/`·`frontend/` 웹 데모 경로를 제공한다. CLI 패키지(`lingo/`)의 테스트·설치 검증과 웹 데모의 컨테이너 readback은 별도 증거로 취급한다.
- 웹 데모는 CI 번역 게이트의 대체가 아니며, fallback·QA 장애·승인·인증 한계를 유지한다.
