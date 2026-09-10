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

## 로컬 실행

```bash
pip install -r requirements-translate.txt

export LLM_GATEWAY_URL="https://your-gateway.example.com/v1"
export LLM_API_KEY="your-api-key"
export LLM_TRANSLATION_MODEL="govail/thinker"
export LLM_REVIEW_MODEL="govail/thinker"
export LLM_TIMEOUT_SECONDS="240"

python translate.py \
  --source path/to/locales/ko.json \
  --base-source path/to/locales/ko.previous.json \
  --langs en-US ja-JP \
  --output path/to/locales/ \
  --glossary path/to/glossary.json \
  --report lingo-report.json
```

기본 실행은 추가·변경·누락 키만 번역하고 기존 번역을 보존한다. 전체 재번역은 명시적인 `--sync-all`에서만 수행한다.

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
