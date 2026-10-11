from __future__ import annotations

from lingo.runtimes.base import (
    BaseRuntimeProvider,
    RuntimeEvent,
    RuntimeMetrics,
    RuntimeObserver,
    TranslationResult,
    TranslationTask,
)
from lingo.runtimes.registry import RuntimeRegistry

_LAZY_PROVIDER_MODULES = {
    "LangGraphRuntimeProvider": "lingo.runtimes.langgraph_provider",
    "EngineProcessRuntimeProvider": "lingo.runtimes.engine_process_provider",
    "MockRuntimeProvider": "lingo.runtimes.mock_provider",
}


def __getattr__(name: str):
    """선택한 concrete Provider만 지연 import합니다."""
    module_name = _LAZY_PROVIDER_MODULES.get(name)
    if module_name is None:
        raise AttributeError(name)

    from importlib import import_module

    module = import_module(module_name)
    value = getattr(module, name)
    globals()[name] = value
    return value

__all__ = [
    "BaseRuntimeProvider",
    "RuntimeEvent",
    "RuntimeMetrics",
    "RuntimeObserver",
    "TranslationTask",
    "TranslationResult",
    "LangGraphRuntimeProvider",
    "EngineProcessRuntimeProvider",
    "MockRuntimeProvider",
    "RuntimeRegistry",
]
