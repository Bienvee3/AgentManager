"""Agent sources."""

from __future__ import annotations

from pydantic import ValidationError

from .config import Settings
from .models import AgentState, Status


def load_agents(settings: Settings) -> list[AgentState]:
    # INTEGRATION POINT: replace this function to load agents from another source
    # (another file, a GET to your own backend, a scan of Open Interpreter
    # profiles...). It only has to return the same list of AgentState.
    if settings.agents_source == "omp" and settings.project is not None:
        from .omp_source import discover_roster

        return discover_roster(settings.project)
    agents: list[AgentState] = []
    seen: set[str] = set()
    for index, raw in enumerate(settings.agents_raw):
        if not isinstance(raw, dict) or "id" not in raw:
            raise SystemExit(f"Invalid agent entry #{index} in config: {raw!r}")
        agent_id = str(raw["id"])
        if agent_id in seen:
            raise SystemExit(f"Duplicate agent id '{agent_id}' in config")
        seen.add(agent_id)
        try:
            agents.append(
                AgentState(
                    id=agent_id,
                    name=str(raw.get("name") or agent_id),
                    role=str(raw.get("role") or ""),
                    avatar=raw.get("avatar"),
                    desk=index,
                    source="config",
                    status=Status.offline,
                    heartbeat_interval_s=raw.get("heartbeat_interval_s"),
                )
            )
        except ValidationError as exc:
            raise SystemExit(f"Invalid agent '{agent_id}' in config: {exc.errors()[0]['msg']}") from None
    return agents
