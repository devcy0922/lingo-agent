from __future__ import annotations

import logging
import os
from typing import Any, Dict, List, Optional, Type

from lingo.runtimes.base import BaseRuntimeProvider, TranslationResult, TranslationTask
from lingo.runtimes.engine_process_provider import EngineProcessRuntimeProvider
from lingo.runtimes.langgraph_provider import LangGraphRuntimeProvider
from lingo.runtimes.mock_provider import MockRuntimeProvider

logger = logging.getLogger("lingo.runtimes.registry")


class RuntimeRegistry:
    """번역 런타임 공급자 관리, 동적 스위칭 및 비교 벤치마킹 레지스트리."""

    _instances: Dict[str, BaseRuntimeProvider] = {}
    _factories: Dict[str, Type[BaseRuntimeProvider]] = {
        "langgraph": LangGraphRuntimeProvider,
        "engine-process": EngineProcessRuntimeProvider,
        "mock": MockRuntimeProvider,
    }

    @classmethod
    def register(cls, name: str, factory: Type[BaseRuntimeProvider]) -> None:
        """새로운 런타임 공급자 클래스를 등록합니다."""
        cls._factories[name.lower()] = factory
        if name.lower() in cls._instances:
            del cls._instances[name.lower()]

    @classmethod
    def register_instance(cls, name: str, provider: BaseRuntimeProvider) -> None:
        """기존에 초기화된 공급자 인스턴스를 직접 등록합니다."""
        cls._instances[name.lower()] = provider

    @classmethod
    def get_provider(cls, name: Optional[str] = None) -> BaseRuntimeProvider:
        """요청된 이름 또는 환경변수(LINGO_RUNTIME_PROVIDER)에 따른 런타임 공급자를 반환합니다."""
        target = (name or os.getenv("LINGO_RUNTIME_PROVIDER", "langgraph")).lower()

        if target in cls._instances:
            return cls._instances[target]

        if target in cls._factories:
            provider = cls._factories[target]()
            cls._instances[target] = provider
            return provider

        available = list(cls._factories.keys())
        raise ValueError(f"알 수 없는 런타임 '{target}'. 사용 가능한 런타임: {', '.join(available)}")

    @classmethod
    def benchmark_runtimes(
        cls,
        task: TranslationTask,
        providers: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """동일한 번역 작업에 대해 복수의 런타임을 나란히 실행하고 성능과 품질을 비교 분석합니다."""
        target_names = providers or ["langgraph", "engine-process"]
        results: Dict[str, TranslationResult] = {}
        comparison: List[Dict[str, Any]] = []

        for p_name in target_names:
            provider = cls.get_provider(p_name)
            logger.info(f"런타임 벤치마크 실행: {p_name}")
            res = provider.execute(task)
            results[p_name] = res

            comparison.append({
                "provider": p_name,
                "status": res.status,
                "duration_ms": res.metrics.total_duration_ms,
                "qa_score": res.metrics.qa_score,
                "retry_count": res.metrics.retry_count,
                "item_count": res.metrics.item_count,
                "stage_durations": res.metrics.stage_durations_ms,
                "error": res.error_message,
            })

        return {
            "task_id": task.task_id,
            "target_lang": task.target_lang,
            "comparison": comparison,
            "results": {k: v.to_dict() for k, v in results.items()},
        }
