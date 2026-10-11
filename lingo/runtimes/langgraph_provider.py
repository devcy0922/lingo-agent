from __future__ import annotations

import logging
import time
from typing import Any, Iterator, List, Optional

from lingo.runtimes.base import (
    BaseRuntimeProvider,
    RuntimeEvent,
    RuntimeMetrics,
    RuntimeObserver,
    TranslationTask,
    TranslationResult,
)
from lingo.runtimes.langgraph.graph import build_translation_graph
from lingo.runtimes.langgraph.nodes import TranslationNodeContext
from lingo.runtimes.langgraph.state import LangGraphState

logger = logging.getLogger("lingo.runtimes.langgraph_provider")


class LangGraphRuntimeProvider(BaseRuntimeProvider):
    """LangGraph 기반 StateGraph 번역 런타임 공급자."""

    def __init__(self, context: Optional[TranslationNodeContext] = None):
        self.context = context or TranslationNodeContext()
        self.graph = build_translation_graph(self.context)

    @property
    def name(self) -> str:
        return "langgraph"

    def execute(
        self,
        task: TranslationTask,
        observer: Optional[RuntimeObserver] = None,
    ) -> TranslationResult:
        start_time = time.time()
        stage_durations: dict[str, float] = {}
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

        emit("init", "INFO", f"LangGraph 런타임 시작 (대상: {task.target_lang})")

        init_state: LangGraphState = {
            "task_id": task.task_id,
            "source_lang": task.source_lang,
            "target_lang": task.target_lang,
            "content_type": task.content_type,
            "raw_payload": task.payload,
            "profile": task.profile,
            "max_retries": task.max_retries,
            "retry_count": 0,
            "items": [],
            "events": [],
        }

        config = {"configurable": {"thread_id": task.task_id}}

        last_stage_time = time.time()
        final_state: Optional[dict] = None

        try:
            # LangGraph 스트리밍 실행으로 노드 전이 감지 및 이벤트 발행
            for step_output in self.graph.stream(init_state, config=config):
                now = time.time()
                for node_name, node_state in step_output.items():
                    elapsed_stage = (now - last_stage_time) * 1000.0
                    stage_durations[node_name] = elapsed_stage
                    last_stage_time = now

                    # 노드별 이벤트 통지
                    node_msg = f"노드 [{node_name}] 실행 완료 ({elapsed_stage:.1f}ms)"
                    emit(
                        stage=node_name,
                        level="INFO",
                        message=node_msg,
                        data={
                            "node": node_name,
                            "stage_duration_ms": elapsed_stage,
                            "item_count": len(node_state.get("items", [])),
                        },
                    )
                    final_state = node_state

            total_duration_ms = (time.time() - start_time) * 1000.0

            if not final_state:
                emit("error", "ERROR", "그래프 실행 상태를 회수하지 못했습니다.")
                return TranslationResult(
                    task_id=task.task_id,
                    status="ERROR",
                    provider=self.name,
                    error_message="빈 상태 결과",
                    events=events,
                )

            items = final_state.get("items", [])
            passed_count = sum(1 for i in items if i.get("status") == "passed")
            failed_count = len(items) - passed_count
            qa_summary = final_state.get("qa_summary", {})
            avg_qa = float(qa_summary.get("average_score", 0.0))
            overall_status = final_state.get("overall_status", "SUCCESS")

            metrics = RuntimeMetrics(
                total_duration_ms=total_duration_ms,
                stage_durations_ms=stage_durations,
                retry_count=final_state.get("retry_count", 0),
                item_count=len(items),
                passed_item_count=passed_count,
                failed_item_count=failed_count,
                qa_score=avg_qa,
            )

            emit(
                stage="completed",
                level="INFO" if overall_status == "SUCCESS" else "WARN",
                message=f"LangGraph 파이프라인 완료: 상태={overall_status}, QA평균={avg_qa:.2f}",
                data={"metrics": metrics.to_dict()},
            )

            return TranslationResult(
                task_id=task.task_id,
                status=overall_status,
                provider=self.name,
                translated_payload=final_state.get("output_payload"),
                qa_report=qa_summary,
                metrics=metrics,
                events=events,
            )

        except Exception as e:
            total_duration_ms = (time.time() - start_time) * 1000.0
            logger.exception(f"LangGraph 파이프라인 예외 발생: {e}")
            emit("error", "ERROR", f"예외 발생: {e}", data={"exception": str(e)})

            return TranslationResult(
                task_id=task.task_id,
                status="ERROR",
                provider=self.name,
                metrics=RuntimeMetrics(total_duration_ms=total_duration_ms),
                events=events,
                error_message=str(e),
            )

    def stream(self, task: TranslationTask) -> Iterator[RuntimeEvent]:
        """실시간 스트리밍으로 이벤트를 즉시 yield합니다."""
        event_queue: List[RuntimeEvent] = []

        def on_event(ev: RuntimeEvent) -> None:
            event_queue.append(ev)

        self.execute(task, observer=on_event)
        for ev in event_queue:
            yield ev
