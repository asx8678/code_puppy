"""Runtime API endpoints for the Code Puppy web dashboard."""

from __future__ import annotations

from typing import Any, Dict, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from code_puppy.api.runtime import get_runtime_manager

router = APIRouter()


class PromptRequest(BaseModel):
    prompt: str
    agent: Optional[str] = None
    model: Optional[str] = None


class CancelRequest(BaseModel):
    reason: Optional[str] = None


class BusResponseRequest(BaseModel):
    prompt_id: str
    response_type: str
    value: Optional[str] = None
    confirmed: Optional[bool] = None
    feedback: Optional[str] = None
    selected_index: Optional[int] = None
    selected_value: Optional[str] = None


class ApprovalResponseRequest(BaseModel):
    approval_id: str
    approved: bool
    feedback: Optional[str] = None


@router.get("/status")
async def get_status() -> Dict[str, Any]:
    """Return current runtime status."""
    return get_runtime_manager().get_status()


@router.post("/prompt")
async def submit_prompt(request: PromptRequest) -> Dict[str, Any]:
    """Submit a prompt to Code Puppy."""
    try:
        return await get_runtime_manager().submit_prompt(
            request.prompt,
            agent=request.agent,
            model=request.model,
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/cancel")
async def cancel_run(request: CancelRequest) -> Dict[str, Any]:
    """Cancel the active prompt run."""
    return await get_runtime_manager().cancel_current_run(request.reason)


@router.post("/respond")
async def respond_to_bus_request(request: BusResponseRequest) -> Dict[str, Any]:
    """Respond to a MessageBus user interaction request."""
    try:
        return get_runtime_manager().respond_to_bus_request(
            prompt_id=request.prompt_id,
            response_type=request.response_type,
            value=request.value,
            confirmed=request.confirmed,
            feedback=request.feedback,
            selected_index=request.selected_index,
            selected_value=request.selected_value,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/approval")
async def respond_to_approval(request: ApprovalResponseRequest) -> Dict[str, Any]:
    """Respond to a browser-backed approval request."""
    try:
        return get_runtime_manager().respond_to_approval(
            request.approval_id,
            request.approved,
            request.feedback,
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.delete("/events")
async def clear_events() -> Dict[str, Any]:
    """Clear the recent event replay buffer."""
    from code_puppy.plugins.frontend_emitter.emitter import clear_recent_events

    clear_recent_events()
    return {"ok": True}
