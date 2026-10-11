from __future__ import annotations

import logging
from typing import Any, Callable, Dict, Literal, Optional

from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph

from lingo.runtimes.langgraph.nodes import TranslationNodeContext, create_nodes
from lingo.runtimes.langgraph.state import LangGraphState

logger = logging.getLogger("lingo.runtimes.langgraph.graph")


def should_retry_or_assemble(state: LangGraphState) -> Literal["draft_translate", "assemble"]:
    """린트나 QA에 실패한 아이템이 있고 재시도 한도 내인 경우 재번역 노드로 루프백합니다."""
    items = state.get("items", [])
    has_failed = any(i.get("status") != "passed" for i in items)
    current_retry = state.get("retry_count", 0)
    max_retries = state.get("max_retries", 2)

    if has_failed and current_retry < max_retries:
        logger.info(
            f"LangGraph 루프백: 미합격 세그먼트 존재. 재시도 ({current_retry + 1}/{max_retries})"
        )
        return "draft_translate"

    return "assemble"


def build_translation_graph(
    context: Optional[TranslationNodeContext] = None,
    checkpointer: Optional[Any] = None,
):
    """LangGraph 상태 머신을 빌드하고 컴파일하여 반환합니다."""
    prepare_node, draft_node, lint_node, qa_node, assemble_node = create_nodes(context)

    builder = StateGraph(LangGraphState)

    # 노드 등록
    builder.add_node("prepare", prepare_node)
    builder.add_node("draft_translate", draft_node)
    builder.add_node("lint", lint_node)
    builder.add_node("qa_judge", qa_node)
    builder.add_node("assemble", assemble_node)

    # 엣지 연결
    builder.add_edge(START, "prepare")
    builder.add_edge("prepare", "draft_translate")
    builder.add_edge("draft_translate", "lint")
    builder.add_edge("lint", "qa_judge")

    # 조건부 루프백 엣지 (피드백 기반 재시도)
    builder.add_conditional_edges(
        "qa_judge",
        should_retry_or_assemble,
        {
            "draft_translate": "draft_translate",
            "assemble": "assemble",
        },
    )

    builder.add_edge("assemble", END)

    cp = checkpointer if checkpointer is not None else MemorySaver()
    compiled = builder.compile(checkpointer=cp)
    return compiled
