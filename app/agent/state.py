from typing import TypedDict, Union, Dict, Any, List, Optional


class AgentState(TypedDict):
    user_id: str
    metric: str
    latest_value: Union[float, Dict[str, Any]]
    recorded_at: str
    history: List[Dict[str, Any]]
    anomaly_detected: bool
    deviation_pct: Optional[float]
    insight: Optional[str]
    chat_mode: bool
    chat_question: Optional[str]
    error: Optional[str]
