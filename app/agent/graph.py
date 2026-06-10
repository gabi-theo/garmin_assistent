from langgraph.graph import StateGraph, END
from app.agent.state import AgentState
from app.agent.nodes import (
    ingest_metrics,
    detect_anomaly,
    retrieve_history,
    generate_insight,
    persist_results,
)


def route_entry(state: AgentState) -> str:
    """Determine the entry point of the graph based on chat_mode."""
    if state.get("chat_mode", False):
        return "retrieve_history"
    return "ingest_metrics"


def route_anomaly(state: AgentState) -> str:
    """Route to retrieve_history if an anomaly is detected, else skip to persist."""
    if state.get("anomaly_detected", False):
        return "retrieve_history"
    return "persist_results"


def route_post_insight(state: AgentState) -> str:
    """Route to END if in chat mode (no DB persistence needed), else persist results."""
    if state.get("chat_mode", False):
        return END
    return "persist_results"


# Define the graph
workflow = StateGraph(AgentState)

# Add all nodes
workflow.add_node("ingest_metrics", ingest_metrics)
workflow.add_node("detect_anomaly", detect_anomaly)
workflow.add_node("retrieve_history", retrieve_history)
workflow.add_node("generate_insight", generate_insight)
workflow.add_node("persist_results", persist_results)

# Configure entry point router
workflow.set_conditional_entry_point(
    route_entry,
    {
        "retrieve_history": "retrieve_history",
        "ingest_metrics": "ingest_metrics",
    }
)

# Standard ingest path transitions
workflow.add_edge("ingest_metrics", "detect_anomaly")

# Route after anomaly detection
workflow.add_conditional_edges(
    "detect_anomaly",
    route_anomaly,
    {
        "retrieve_history": "retrieve_history",
        "persist_results": "persist_results",
    }
)

# After fetching history, always run insight generation
workflow.add_edge("retrieve_history", "generate_insight")

# Route after insight generation (chat ends here, metric pipeline persists)
workflow.add_conditional_edges(
    "generate_insight",
    route_post_insight,
    {
        END: END,
        "persist_results": "persist_results",
    }
)

# Final step for ingestion path
workflow.add_edge("persist_results", END)

# Compile graph
agent_graph = workflow.compile()
