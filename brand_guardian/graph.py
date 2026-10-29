"""LangGraph DAG wiring: ingest -> index -> retrieve -> audit, short-circuiting on errors."""

from typing import Any, Callable

from langgraph.graph import END, START, StateGraph

from brand_guardian import nodes
from brand_guardian.state import AuditState


def _continue_or_end(next_node: str) -> Callable[[AuditState], str]:
    def route(state: AuditState) -> str:
        return END if state.get("errors") else next_node

    return route


def build_graph():
    g = StateGraph(AuditState)
    g.add_node("ingest", nodes.ingest_node)
    g.add_node("index", nodes.index_node)
    g.add_node("retrieve", nodes.retrieve_node)
    g.add_node("audit", nodes.audit_node)

    g.add_edge(START, "ingest")
    g.add_conditional_edges("ingest", _continue_or_end("index"), ["index", END])
    g.add_conditional_edges("index", _continue_or_end("retrieve"), ["retrieve", END])
    g.add_conditional_edges("retrieve", _continue_or_end("audit"), ["audit", END])
    g.add_edge("audit", END)
    return g.compile()


def run_audit(video_url: str) -> dict[str, Any]:
    """Run the full pipeline and return the final state (report and/or errors)."""
    return build_graph().invoke({"video_url": video_url, "errors": []})
