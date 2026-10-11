from __future__ import annotations

import logging
import os
from importlib import import_module
from typing import Any, Callable, Dict, List, Optional, Type

from lingo.runtimes.base import BaseRuntimeProvider, TranslationResult, TranslationTask

logger = logging.getLogger("lingo.runtimes.registry")

ProviderFactory = Callable[[], BaseRuntimeProvider]


def _lazy_provider_factory(module_name: str, class_name: str) -> ProviderFactory:
    """선택된 Provider만 import하도록 지연 로더를 만듭니다."""

    def factory() -> BaseRuntimeProvider:
        try:
            module = import_module(module_name)
            provider_cls = getattr(module, class_name)
            return provider_cls()
        except (ImportError, AttributeError) as exc:
            raise RuntimeError(
                f"Provider '{class_name}'를 불러올 수 없습니다. "
                f"해당 런타임 의존성을 설치했는지 확인하세요: {exc}"
            ) from exc

    return factory


class RuntimeRegistry:
    """번역 런타임 공급자 관리, 동적 스위칭 및 비교 벤치마킹 레지스트리."""

    _instances: Dict[str, BaseRuntimeProvider] = {}
    # Provider 구현은 선택 시점까지 import하지 않는다. 따라서 LangGraph가
    # 없는 설치에서 engine-process Provider만 등록·사용할 수 있다.
    _factories: Dict[str, ProviderFactory] = {
        "langgraph": _lazy_provider_factory(
            "lingo.runtimes.langgraph_provider", "LangGraphRuntimeProvider"
        ),
        "engine-process": _lazy_provider_factory(
            "lingo.runtimes.engine_process_provider", "EngineProcessRuntimeProvider"
        ),
        "mock": _lazy_provider_factory(
            "lingo.runtimes.mock_provider", "MockRuntimeProvider"
        ),
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
        target = (name or os.getenv("LINGO_RUNTIME_PROVIDER") or cls._default_provider_name()).lower()

        if target in cls._instances:
            return cls._instances[target]

        if target in cls._factories:
            provider = cls._factories[target]()
            cls._instances[target] = provider
            return provider

        available = list(cls._factories.keys())
        raise ValueError(f"알 수 없는 런타임 '{target}'. 사용 가능한 런타임: {', '.join(available)}")

    @classmethod
    def _default_provider_name(cls) -> str:
        """현재 설치에서 사용 가능한 기본 Provider 이름을 결정합니다."""
        try:
            import_module("langgraph")
        except ImportError:
            return "engine-process"
        return "langgraph"

    @classmethod
    def benchmark_runtimes(
        cls,
        task: TranslationTask,
        providers: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """동일한 번역 작업에 대해 복수의 런타임을 나란히 실행하고 성능과 품질을 비교 분석합니다."""
        target_names = providers or [
            os.getenv("LINGO_RUNTIME_PROVIDER") or cls._default_provider_name()
        ]
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
