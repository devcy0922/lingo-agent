from __future__ import annotations

import json
import logging
import os
import time
import uuid
from typing import Any, Dict, Iterator, List, Optional

import httpx

from lingo.runtimes.base import (
    BaseRuntimeProvider,
    RuntimeEvent,
    RuntimeMetrics,
    RuntimeObserver,
    TranslationResult,
    TranslationTask,
)

logger = logging.getLogger("lingo.runtimes.engine_process_provider")


class EngineProcessRuntimeProvider(BaseRuntimeProvider):
    """사내 engine-process (cy-process CLI 또는 HTTP /v1/process/*) 연계 런타임 공급자."""

    def __init__(
        self,
        endpoint_url: Optional[str] = None,
        auth_token: Optional[str] = None,
        timeout: float = 60.0,
        allow_fallback: bool = False,
    ):
        self.endpoint_url = endpoint_url or os.getenv("CY_PROCESS_URL", "http://127.0.0.1:8095")
        self.auth_token = auth_token or os.getenv("CY_PROCESS_AUTH_TOKEN") or os.getenv("CY_PROCESS_HTTP_TOKEN", "")
        self.timeout = timeout
        self.allow_fallback = allow_fallback

    @property
    def name(self) -> str:
        return "engine-process"

    def execute(
        self,
        task: TranslationTask,
        observer: Optional[RuntimeObserver] = None,
    ) -> TranslationResult:
        start_time = time.time()
        stage_durations: Dict[str, float] = {}
        events: List[RuntimeEvent] = []

        def emit(stage: str, level: str, message: str, data: Optional[dict] = None) -> RuntimeEvent:
            ev = RuntimeEvent(
                task_id=task.task_id,
                provider=self.name,
                stage=stage,
                level=level,
                message=message,
                data=data or {},
            )
            events.append(ev)
            if observer:
                try:
                    observer(ev)
                except Exception as err:
                    logger.warning(f"Observer callback error: {err}")
            return ev

        emit("init", "INFO", f"engine-process 런타임 호출 준비 (엔드포인트: {self.endpoint_url})")

        headers = {"Content-Type": "application/json"}
        if self.auth_token:
            headers["Authorization"] = f"Bearer {self.auth_token}"

        source_json = json.dumps(task.payload, ensure_ascii=False, sort_keys=True)
        session_id = f"lingo-benchmark-{uuid.uuid4().hex[:12]}"
        operation_id = f"{task.task_id}-{uuid.uuid4().hex[:12]}"
        payload = {
            "sessionId": session_id,
            "operationId": operation_id,
            "responseFormat": "json_object",
            "maxTurns": 1,
            "message": (
                "Translate the following Newsroom article from "
                f"{task.source_lang} to {task.target_lang}. Return exactly one JSON object. "
                "Preserve every key, ArticleBlock type, array length, id, slug, category, "
                "content_type, numeric value, and metadata field. Translate only human-readable "
                "headline, dek, paragraph/subhead/bullet text, keynumber labels and notes. "
                "Do not add commentary outside the JSON object.\n\n"
                f"SOURCE_ARTICLE_JSON:\n{source_json}"
            ),
            "customInstructions": (
                "You are a translation runtime adapter. Preserve the input JSON schema exactly. "
                f"Use target language {task.target_lang}."
            ),
        }

        t0 = time.time()
        try:
            emit("dispatch", "INFO", "engine-process 작업 제출 (/v1/process/runs)")
            # HTTP 엔드포인트 호출 시도
            resp = None
            try:
                with httpx.Client(timeout=self.timeout) as client:
                    resp = client.post(
                        f"{self.endpoint_url.rstrip('/')}/v1/process/runs",
                        headers=headers,
                        json=payload,
                    )
            except Exception as net_err:
                logger.info(f"engine-process 데몬 직결 실패: {net_err}")

            stage_durations["dispatch"] = (time.time() - t0) * 1000.0

            if resp and resp.is_success:
                res_data = resp.json()
                t1 = time.time()
                emit(
                    "execute",
                    "INFO",
                    "engine-process 작업 완료 수신",
                    data={"run_id": res_data.get("runId"), "operation_id": res_data.get("operationId")},
                )
                stage_durations["execute"] = (time.time() - t1) * 1000.0

                raw_output = res_data.get("response")
                translated_payload = raw_output
                output_error: Optional[str] = None
                if isinstance(raw_output, str):
                    try:
                        translated_payload = json.loads(raw_output)
                    except json.JSONDecodeError:
                        output_error = "engine-process returned non-JSON translation output"
                elif not isinstance(raw_output, dict):
                    output_error = "engine-process response field is not a JSON object"

                upstream_error = bool(res_data.get("isError"))
                if upstream_error:
                    output_error = "engine-process reported an execution error"
                token_usage = {
                    key: res_data[key]
                    for key in ("inputTokens", "outputTokens")
                    if isinstance(res_data.get(key), int)
                }
                total_ms = (time.time() - start_time) * 1000.0
                execution_status = "ERROR" if output_error else "SUCCESS"
                metrics = RuntimeMetrics(
                    total_duration_ms=float(res_data.get("durationMs", total_ms)),
                    stage_durations_ms=stage_durations,
                    item_count=res_data.get("item_count", 1),
                    passed_item_count=1 if execution_status == "SUCCESS" else 0,
                    failed_item_count=1 if execution_status != "SUCCESS" else 0,
                    token_usage=token_usage,
                )
                qa_report = {
                    "status": "UNVERIFIED" if execution_status == "SUCCESS" else "ERROR",
                    "quality_verified": False,
                    "adapter": "engine-process-http",
                }
                qa_report["evidence"] = {
                    "mode": "engine-process-http",
                    "live_runtime": True,
                    "upstream_reachable": True,
                    "fallback_used": False,
                    "upstream_http_status": resp.status_code,
                }
                return TranslationResult(
                    task_id=task.task_id,
                    status=execution_status,
                    provider=self.name,
                    translated_payload=translated_payload if output_error is None else None,
                    qa_report=qa_report,
                    metrics=metrics,
                    events=events,
                    error_message=output_error,
                )

            upstream_reason = (
                "engine-process endpoint unavailable"
                if resp is None
                else f"engine-process returned HTTP {resp.status_code}"
            )

            # 로컬 어댑터는 명시적으로 요청한 경우에만 실행하며, 결과를
            # 승인 가능한 성공 번역으로 승격하지 않는다.
            if self.allow_fallback:
                t_fb = time.time()
                emit(
                    "fallback_runner",
                    "WARN",
                    "engine-process 연결 실패로 로컬 어댑터 실행",
                    data={"fallback_used": True, "reason": upstream_reason},
                )
                fallback_out = self._run_process_fallback(task)
                stage_durations["fallback_runner"] = (time.time() - t_fb) * 1000.0
                total_ms = (time.time() - start_time) * 1000.0
                metrics = RuntimeMetrics(
                    total_duration_ms=total_ms,
                    stage_durations_ms=stage_durations,
                    item_count=1,
                    failed_item_count=1,
                )
                emit("completed", "WARN", "로컬 어댑터 결과는 DEGRADED로 기록")
                return TranslationResult(
                    task_id=task.task_id,
                    status="DEGRADED",
                    provider=self.name,
                    translated_payload=fallback_out,
                    qa_report={
                        "status": "DEGRADED",
                        "adapter": "engine-process-local",
                        "fallback_used": True,
                        "evidence": {
                            "mode": "local_adapter",
                            "live_runtime": False,
                            "fallback_used": True,
                        },
                        "reason": upstream_reason,
                    },
                    metrics=metrics,
                    events=events,
                    error_message=upstream_reason,
                )

            total_ms = (time.time() - start_time) * 1000.0
            emit("error", "ERROR", upstream_reason)
            return TranslationResult(
                task_id=task.task_id,
                status="ERROR",
                provider=self.name,
                qa_report={
                    "status": "UNAVAILABLE",
                    "adapter": "engine-process-http",
                    "fallback_used": False,
                    "evidence": {
                        "mode": "engine-process-http",
                        "live_runtime": False,
                        "upstream_reachable": resp is not None,
                        "fallback_used": False,
                        **({"upstream_http_status": resp.status_code} if resp is not None else {}),
                    },
                },
                metrics=RuntimeMetrics(
                    total_duration_ms=total_ms,
                    stage_durations_ms=stage_durations,
                    item_count=1,
                    failed_item_count=1,
                ),
                events=events,
                error_message=upstream_reason,
            )

        except Exception as e:
            total_ms = (time.time() - start_time) * 1000.0
            logger.exception(f"engine-process 실행 오류: {e}")
            emit("error", "ERROR", f"실행 실패: {e}")
            return TranslationResult(
                task_id=task.task_id,
                status="ERROR",
                provider=self.name,
                metrics=RuntimeMetrics(total_duration_ms=total_ms),
                events=events,
                error_message=str(e),
            )

    def _run_process_fallback(self, task: TranslationTask) -> Any:
        """독립적인 프로세스 시뮬레이션 변환 로직."""
        payload = task.payload
        tgt = task.target_lang.upper()
        if isinstance(payload, dict):
            out = dict(payload)
            if "headline" in out:
                out["headline"] = f"[{tgt}] {out['headline']}"
            if "dek" in out:
                out["dek"] = f"[{tgt}] {out['dek']}"
            return out
        elif isinstance(payload, str):
            return f"[{tgt}] {payload}"
        return payload
