"""호환용 graph facade. 구현은 langgraph-process가 소유한다."""

from langgraph_process.graph import build_translation_graph, should_retry_or_assemble

__all__ = ["build_translation_graph", "should_retry_or_assemble"]
