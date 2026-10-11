from __future__ import annotations

import time
from typing import Any, List, Optional

from lingo.runtimes.base import (
    BaseRuntimeProvider,
    RuntimeEvent,
    RuntimeMetrics,
    RuntimeObserver,
    TranslationResult,
    TranslationTask,
)


class MockRuntimeProvider(BaseRuntimeProvider):
    """테스트 및 결정론적 검증을 위한 경량 Mock 런타임 공급자."""

    def __init__(self, force_qa_score: float = 4.5, force_status: str = "SUCCESS"):
        self.force_qa_score = force_qa_score
        self.force_status = force_status

    @property
    def name(self) -> str:
        return "mock"

    def execute(
        self,
        task: TranslationTask,
        observer: Optional[RuntimeObserver] = None,
    ) -> TranslationResult:
        t0 = time.time()
        events: List[RuntimeEvent] = []

        def emit(stage: str, msg: str) -> None:
            ev = RuntimeEvent(
                task_id=task.task_id,
                provider=self.name,
                stage=stage,
                message=msg,
            )
            events.append(ev)
            if observer:
                observer(ev)

        emit("init", "Mock 런타임 시작")
        emit("translate", "Mock 번역 처리 완료")
        emit("qa", f"Mock QA 판정 (점수: {self.force_qa_score})")

        out_payload: Any = None
        tgt = task.target_lang.upper()
        if isinstance(task.payload, dict):
            out_payload = dict(task.payload)
            if "headline" in out_payload:
                out_payload["headline"] = f"[{tgt}] {out_payload['headline']}"
            if "dek" in out_payload:
                out_payload["dek"] = f"[{tgt}] {out_payload['dek']}"
        elif isinstance(task.payload, str):
            out_payload = f"[{tgt}] {task.payload}"
        else:
            out_payload = task.payload

        total_ms = (time.time() - t0) * 1000.0
        emit("complete", "Mock 런타임 종료")

        return TranslationResult(
            task_id=task.task_id,
            status=self.force_status,
            provider=self.name,
            translated_payload=out_payload,
            qa_report={"score": self.force_qa_score, "advisory": "mock"},
            metrics=RuntimeMetrics(
                total_duration_ms=total_ms,
                item_count=1,
                passed_item_count=1,
                qa_score=self.force_qa_score,
            ),
            events=events,
        )
