"""ReAct agent chat endpoint (/v1/agent/chat)."""
from __future__ import annotations

from fastapi import APIRouter, Depends, status

from app.agent.react import run_react_agent
from app.config import Settings, get_settings
from app.deps import verify_api_key
from app.schemas.agent import AgentRequest, AgentResponse

router = APIRouter(prefix="/v1", tags=["agent"])


@router.post(
    "/agent/chat",
    response_model=AgentResponse,
    status_code=status.HTTP_200_OK,
    dependencies=[Depends(verify_api_key)],
)
def agent_chat(
    request: AgentRequest,
    settings: Settings = Depends(get_settings),
) -> AgentResponse:
    """Run the bounded ReAct agent loop for a user turn with optional session continuity."""
    return run_react_agent(
        request.message,
        session_id=request.session_id,
        settings=settings,
    )
