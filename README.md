# LingoAgent

ko.json을 원본으로 LLM 번역 → ICU 검증 → QA → GitHub Action 자동 커밋까지 연결하는 **i18n 번역 배포 게이트**입니다.

> **실제 적용**: [devcy0922.github.io](https://devcy0922.github.io) 포트폴리오 사이트의 영문(en)/일문(ja) UI 텍스트를 이 파이프라인이 번역합니다.
> `docs/public/locales/ko.json` 변경 → GitHub Action → 검증 통과 시만 `en.json` / `ja.json` 자동 커밋.

---

## 핵심 원칙

LLM 번역 결과를 그대로 믿지 않는다. 정적 검증과 QA를 통과한 번역만 커밋된다.

| 조건 | 결과 |
|---|---|
| LLM 장애 → Fallback 번역 (`is_fallback=True`) | `exit(1)` → 커밋 차단 |
| ICU 변수 누락 / 키 불일치 (lint 실패) | 재시도 → 3회 초과 시 `exit(2)` |
| QA 점수 < 85 / QA API 장애 | `exit(2)` → 기본 통과 점수 부여 금지 |
| 모든 검증 통과 | en.json, ja.json 커밋 |

---

## 구성

```
lingo-agent/
├── translate.py              # 독립 실행 번역 CLI (httpx만 의존)
├── requirements-translate.txt # GitHub Action 설치 의존성
└── backend/                  # FastAPI 데모 UI (로컬 시연용)
    ├── agent.py
    ├── main.py
    └── ...
```

---

## 빠른 시작 — translate.py (GitHub Action / 로컬 CLI)

```bash
# 의존성 설치
pip install -r requirements-translate.txt

# 환경변수
export LLM_GATEWAY_URL="https://your-gateway.example.com/v1"
export LLM_API_KEY="your-api-key"
export LLM_MODEL="auto"

# 번역 실행
python translate.py \
  --source path/to/ko.json \
  --langs en-US ja-JP \
  --output path/to/locales/

# 검증만 (파일 저장 없음)
python translate.py --source ko.json --langs en-US ja-JP --output . --dry-run
```

### 종료 코드

| 코드 | 의미 |
|---|---|
| `0` | 모든 언어 번역 완료 — 커밋 가능 |
| `1` | Fallback 번역 발생 — 커밋 차단 |
| `2` | Lint / QA 검증 실패 — 커밋 차단 |
| `3` | 파일 I/O 오류 |

---

## GitHub Action 연동

포트폴리오 사이트(`.github/workflows/translate-i18n.yml`)에서 이 레포의 `translate.py`를 직접 참조합니다.

```yaml
- uses: actions/checkout@v4
  with:
    repository: devcy0922/lingo-agent
    path: .lingo-agent
    sparse-checkout: |
      translate.py
      requirements-translate.txt

- run: python .lingo-agent/translate.py --source ko.json --langs en-US ja-JP --output locales/
  env:
    LLM_GATEWAY_URL: ${{ secrets.LLM_GATEWAY_URL }}
    LLM_API_KEY:     ${{ secrets.LLM_API_KEY }}
```

---

## 데모 UI (FastAPI 로컬 서버)

번역 파이프라인을 웹 콘솔로 시연하려면 백엔드 서버를 사용합니다.

```bash
# 환경변수 설정
cp .env.example .env

# 가상환경 및 의존성
python3 -m venv .venv && source .venv/bin/activate
pip install -r backend/requirements.txt

# 프론트엔드 빌드 + 백엔드 실행
pnpm install && pnpm build:frontend && pnpm start:backend
# → http://localhost:9095
```

---

## 기술 스택

| 컴포넌트 | 기술 |
|---|---|
| 번역 CLI | Python 3.11, httpx |
| ICU 린터 | 정규식 기반 (plural/select, 중첩 JSON) |
| QA Judge | LLM-as-a-Judge, 85점 컷오프, 3회 재시도 |
| CI/CD | GitHub Actions |
| 데모 UI | FastAPI, SQLite, React, TypeScript |
