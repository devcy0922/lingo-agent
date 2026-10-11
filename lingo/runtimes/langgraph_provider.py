"""호환용 facade.

LangGraph Provider의 실제 구현은 독립 저장소에 있다.
https://github.com/devcy0922/langgraph-process
"""

from langgraph_process import LangGraphRuntimeProvider

__all__ = ["LangGraphRuntimeProvider"]
