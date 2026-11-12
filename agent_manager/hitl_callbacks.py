"""Hooks invoked after a HITL decision is made."""

from __future__ import annotations

from .models import AgentState, Approval

# INTEGRATION POINT: react to decisions in your own system. Example:
#
#   import httpx
#
#   async def on_approved(approval, agent):
#       async with httpx.AsyncClient() as client:
#           await client.post(
#               "http://localhost:XXXX/your-endpoint",
#               json=approval.model_dump(mode="json"),
#           )


async def on_approved(approval: Approval, agent: AgentState) -> None:
    return None


async def on_rejected(approval: Approval, agent: AgentState) -> None:
    # Also called when the approval expired (approval.status == "expired").
    return None
