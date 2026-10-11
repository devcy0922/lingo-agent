"""호환용 state facade. 구현은 langgraph-process가 소유한다."""

from langgraph_process.state import LangGraphState, TranslationItem

__all__ = ["LangGraphState", "TranslationItem"]
