from __future__ import annotations

import time
import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, Iterator, List, Optional

from lingo.types import ProfileConfig


@dataclass
class RuntimeEvent:
    """런타임 실행 중 발생하는 단계별 관측 이벤트."""
    task_id: str
    provider: str
    stage: str
    level: str = "INFO"  # INFO, WARN, ERROR
    message: str = ""
    data: Dict[str, Any] = field(default_factory=dict)
    timestamp: float = field(default_factory=time.time)
    event_id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])

    def to_dict(self) -> Dict[str, Any]:
        return {
            "event_id": self.event_id,
            "timestamp": self.timestamp,
            "task_id": self.task_id,
            "provider": self.provider,
            "stage": self.stage,
            "level": self.level,
            "message": self.message,
            "data": self.data,
        }


RuntimeObserver = Callable[[RuntimeEvent], None]


@dataclass
class RuntimeMetrics:
    """런타임 실행 성능 및 리소스 메트릭."""
    total_duration_ms: float = 0.0
    stage_durations_ms: Dict[str, float] = field(default_factory=dict)
    retry_count: int = 0
    item_count: int = 0
    passed_item_count: int = 0
    failed_item_count: int = 0
    qa_score: float = 0.0
    token_usage: Dict[str, int] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "total_duration_ms": round(self.total_duration_ms, 2),
            "stage_durations_ms": {k: round(v, 2) for k, v in self.stage_durations_ms.items()},
            "retry_count": self.retry_count,
            "item_count": self.item_count,
            "passed_item_count": self.passed_item_count,
            "failed_item_count": self.failed_item_count,
            "qa_score": round(self.qa_score, 2),
            "token_usage": self.token_usage,
        }


@dataclass
class TranslationTask:
    """런타임에 전달되는 표준화된 번역 작업 계약."""
    task_id: str
    source_lang: str = "ko"
    target_lang: str = "en"
    content_type: str = "article_blocks"  # article_blocks, json, markdown
    payload: Any = None
    profile: Optional[ProfileConfig] = None
    max_retries: int = 2
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class TranslationResult:
    """런타임 실행 결과 표준 객체."""
    task_id: str
    status: str  # SUCCESS, QA_FAILED, ERROR, DEGRADED
    provider: str
    translated_payload: Any = None
    qa_report: Dict[str, Any] = field(default_factory=dict)
    metrics: RuntimeMetrics = field(default_factory=RuntimeMetrics)
    events: List[RuntimeEvent] = field(default_factory=list)
    error_message: Optional[str] = None

    @property
    def is_success(self) -> bool:
        return self.status == "SUCCESS"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "task_id": self.task_id,
            "status": self.status,
            "provider": self.provider,
            "translated_payload": self.translated_payload,
            "qa_report": self.qa_report,
            "metrics": self.metrics.to_dict(),
            "events": [e.to_dict() for e in self.events],
            "error_message": self.error_message,
        }


class BaseRuntimeProvider(ABC):
    """모든 번역 런타임이 구현해야 하는 공통 추상 공급자 인터페이스."""

    @property
    @abstractmethod
    def name(self) -> str:
        """런타임 고유 식별자 (예: 'langgraph', 'engine-process', 'mock')."""
        pass

    @abstractmethod
    def execute(
        self,
        task: TranslationTask,
        observer: Optional[RuntimeObserver] = None,
    ) -> TranslationResult:
        """동기/블로킹 실행으로 최종 결과를 반환합니다."""
        pass

    def stream(
        self,
        task: TranslationTask,
    ) -> Iterator[RuntimeEvent]:
        """스트리밍 실행으로 단계별 이벤트를 실시간 방출합니다."""
        events: List[RuntimeEvent] = []

        def collect(event: RuntimeEvent) -> None:
            events.append(event)

        # 기본 구현: execute 수행 중 수집된 이벤트를 순차 반환
        self.execute(task, observer=collect)
        for ev in events:
            yield ev
