# LingoAgent

LingoAgent는 한국어 i18n 원문을 기준으로 변경된 키만 번역하고, 정적 검증과 LLM QA를 통과한 결과만 소비 저장소에 반영하는 **CI 번역 배포 게이트**다.

상세한 현재 구조와 한계는 [architecture.md](./architecture.md)에 정리되어 있다.

## 핵심 구분

이 레포에는 두 실행 경로가 있다.

| 경로 | 구현 | 역할 | 배포 보장 |
|---|---|---|---|
| CI/CD | `translate.py`, `translate_markdown.py` | locale·Markdown 생성 및 커밋 차단 | fail-closed |
| Web Demo | `backend/`, `frontend/` | 로컬 작업·검토 UI 시연 | production gate 아님 |

웹 데모의 fallback과 기본 QA 점수 처리는 CI 경로의 보장과 다르다. 두 경로를 동일한 번역 엔진으로 설명하지 않는다.

`translate.py`는 JSON locale을, `translate_markdown.py`는 블로그·프로젝트 Markdown을 처리한다. Markdown adapter는 frontmatter와 fenced code/Mermaid를 보존하며, Gateway 장애 시 fallback하지 않는다.

## 1차 통합 테스트

첫 소비 저장소는 `/srv/demo/devcy0922.github.io`다. 현재는 VitePress build/deploy workflow만 있고 locale 파일과 번역 workflow는 아직 없다.

추가할 1차 계약:

```text
docs/public/locales/ko.json          한국어 원문
docs/public/locales/en.json          영어 생성물
docs/public/locales/ja.json          일본어 생성물
docs/public/locales/ko.previous.json 변경 기준 원문
.github/workflows/translate-i18n.yml 번역 게이트
lingo-report.json                    QA 증거 artifact
```

번역과 QA 모델은 1차 테스트에서 모두 `govail/thinker`를 사용한다.

## 통합 CLI (`lingo`)

Lingo는 다른 프로젝트에서 한 줄로 호출할 수 있는 통합 CLI 도구를 제공한다.

### 설치

```bash
# 로컬 개발 환경 또는 CI 설치
pip install -e /srv/internal/lingo-agent
# 또는 pip install -e .
```

### 사용법

```bash
# 1. Markdown 문서 번역 (기술 블로그 프로필 적용)
lingo docs/posts/new-post.md -l en,ja -p tech_blog

# 2. i18n JSON 증분 번역 (Git HEAD 대비 변경된 키만 번역)
lingo locales/ko.json --diff -p internal_admin

# 3. CI 검증 전용 (파일 변경 없이 Fail-Closed 린트 & QA 확인)
lingo check locales/ko.json -l en-US ja-JP
```

## 네임스페이스 기반 용어집 & 번역 메모리 (TM)

프로젝트 특성(기술 블로그 vs 내부 관리자 콘솔 vs B2C)에 따라 톤앤매너와 번역 용어가 충돌하는 문제를 방지하기 위해 **선언적 계층형 프로필**을 제공한다.

```text
Level 1: Global (profiles/global.yml) - 전사 공통 브랜드 및 고유명사
   └── Level 2: Profile (profiles/tech_blog.yml, internal_admin.yml) - 톤앤매너 및 도메인 용어
          └── Level 3: Project Local (.lingo.yml) - 개별 저장소 전용 규칙
```

## 런타임 추상화 및 다국어 오케스트레이션

Lingo는 서비스 계층과 분리된 **런타임 공급자 패턴(Runtime Provider Pattern)**을 제공합니다. 소비자는 `RuntimeRegistry → Provider → Runtime` 경계만 사용하고, LangGraph·engine-process·다른 HTTP/CLI 런타임은 환경별 Provider 구현으로 선택합니다. LangGraph Provider의 실제 구현은 독립 저장소 [`langgraph-process`](https://github.com/devcy0922/langgraph-process)가 소유하며, 이 저장소의 `lingo.runtimes.langgraph*` 경로는 호환 facade입니다.

### 1. 런타임 Provider API
```bash
# 소비자 코드에서 Registry가 선택한 Provider 실행
python - <<'PY'
from lingo.runtimes import RuntimeRegistry, TranslationTask

task = TranslationTask(task_id="example", payload={"headline": "원문"})
result = RuntimeRegistry.get_provider("mock").execute(task)
print(result.provider, result.status)
PY

# 환경에 설치된 Provider를 명시적으로 선택
export LINGO_RUNTIME_PROVIDER=engine-process
```

Provider 호출 경계는 `소비자 → RuntimeRegistry → 선택된 Provider → 런타임`이다. engine-process용 HTTP/CLI 호출은 `EngineProcessRuntimeProvider`가 담당하며, 소비자 코드가 `/v1/process/*`를 직접 호출하지 않는다. 특정 환경에서 engine-process만 사용할 수 있도록 Provider 구현은 지연 import되고 LangGraph Provider는 `langgraph` optional extra로만 설치된다. 따라서 engine-process-only 환경은 `langgraph-process`를 설치하지 않아도 된다.

현재 `lingo` CLI의 JSON/Markdown 번역 경로는 기존 `translate.run_pipeline()`을 사용하며, `--runtime`은 Provider 실행을 보장하지 않는다. CLI까지 Provider로 전환하려면 별도 어댑터 통합과 E2E 검증이 필요하다.

### 2. 크로스 런타임 벤치마킹 (`RuntimeRegistry.benchmark_runtimes`)
동일한 작업(`TranslationTask`)에 대해 **현재 환경에 등록된 Provider만** 나란히 실행하고 소요 시간, QA 점수, 재시도 횟수를 비교 분석할 수 있습니다. 두 런타임이 모두 있는 환경에서만 `langgraph`와 `engine-process`를 함께 지정합니다.

### 3. MCP(Model Context Protocol) 표준 도구
런타임과 독립적으로 호출 가능한 핵심 도구군을 제공합니다:
- `mcp_glossary_lookup`: 프로필별 용어 및 금지어 조회
- `mcp_lint_translation`: ICU 변수, HTML 태그, 금지 구문 무결성 검증
- `mcp_article_blocks_transform`: 뉴스룸 에디토리얼 1열 본문(`ArticleBlock[]`) 구조 보존 치환


- **하드코딩 방지**: 모든 용어와 스타일 지침은 YAML 파일로 선언적 관리.
- **번역 메모리(TM) 격리**: 동일한 한국어 문장이라도 프로필(네임스페이스)별로 분리 저장되어 컨텍스트 오염을 방지.

## 레거시 CLI (`translate.py`) 호환 실행


## 종료 코드

| 코드 | 의미 |
|---|---|
| `0` | 모든 번역 검증 통과, 파일 반영 가능 |
| `1` | fallback 번역 발생, 커밋 차단 |
| `2` | lint 또는 QA 실패, 커밋 차단 |
| `3` | 입력·출력 파일 오류 |

## 검증 원칙

- JSON 구조와 원문/번역문 key parity를 검사한다.
- ICU 변수를 보존한다.
- glossary와 금지 표현을 검사한다.
- 생성된 모든 키를 QA batch로 검수한다.
- QA 실패 시 실패한 키만 feedback 기반으로 재시도한다.
- QA 장애와 fallback은 성공으로 처리하지 않는다.
- report가 성공을 증명하지 못하면 자동 커밋하지 않는다.

## 웹 데모

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r backend/requirements.txt
pnpm install
pnpm build:frontend
pnpm start:backend
```

웹 데모는 FastAPI, SQLite, React 기반의 로컬 시연용 경로다. 재시작 복구, idempotency, 원자적 publish, 인증·인가 등 production hardening은 아직 범위 밖이다.
