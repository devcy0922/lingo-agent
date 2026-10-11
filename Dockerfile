# 1단계: 프론트엔드 빌드
FROM node:20-slim AS frontend-build
WORKDIR /app
COPY pnpm-workspace.yaml package.json pnpm-lock.yaml* ./
COPY frontend ./frontend
RUN corepack enable && corepack prepare pnpm@10.34.5 --activate \
    && pnpm install --frozen-lockfile \
    && pnpm build:frontend

# 2단계: 백엔드 런타임
FROM python:3.12-slim AS runtime
WORKDIR /app

ARG LINGO_VERSION=1.3.0
ARG LINGO_GIT_SHA=unknown

COPY backend/requirements.txt ./backend/requirements.txt
RUN pip install --no-cache-dir -r backend/requirements.txt

COPY backend ./backend
COPY --from=frontend-build /app/frontend/dist ./frontend/dist

ENV HOST=0.0.0.0
ENV LINGO_VERSION=${LINGO_VERSION} LINGO_GIT_SHA=${LINGO_GIT_SHA}
EXPOSE 47081

WORKDIR /app/backend
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "47081"]
