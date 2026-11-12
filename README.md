# Agent Manager

Local server that receives events from AI agents (Open Interpreter CLI and classic library, or your own scripts) and shows them in:

- a pixel-art web office (`http://127.0.0.1:8765/`): one cubicle per agent, colour-coded status tags, human-in-the-loop (HITL) bubbles with approve/reject, a terminal HUD and a status board;
- a Rich terminal UI (`python -m agent_manager watch`) that approves/rejects with the keyboard.

Agents are loaded from data (`agents.yaml` + runtime registration), never hard-coded. No cost/token/consumption metrics are tracked anywhere.

## Install (Windows)

`pip.exe` may be blocked by App Control, so always use `python -m`:

```powershell
python -m venv .venv
.venv\Scripts\python -m pip install -r requirements-dev.txt
copy agents.example.yaml agents.yaml   # optional; the example is used if missing
```

## Run

```powershell
.venv\Scripts\python -m agent_manager serve [--config agents.yaml] [--host 127.0.0.1] [--port 8765]
.venv\Scripts\python -m agent_manager watch [--url http://127.0.0.1:8765]
.venv\Scripts\python -m agent_manager simulate [--url ...] [--seed 1]   # demo agents
.venv\Scripts\python -m pytest -q
```

Config path resolution: `--config`, then `AGENT_MANAGER_CONFIG`, then `./agents.yaml`, then `agents.example.yaml`.
The server listens on `127.0.0.1` only. POSTs require `Content-Type: application/json` and the WebSocket checks `Origin`, so a web page cannot approve actions through localhost.

## Integration points

1. **Agents** — `agent_manager/sources.py::load_agents` (swap the source), `agents.yaml`, or register at runtime with `agent_manager/client.py` (stdlib-only, copy it into any venv):
   ```python
   client = AgentManagerClient("my-agent", name="My Agent"); client.register(); client.start_heartbeat()
   decision = client.request_approval("Deploy", details="...", kind="deploy")
   ```
2. **HITL callbacks (backend)** — `agent_manager/hitl_callbacks.py` (`on_approved` / `on_rejected`, the latter also on expiry).
3. **HITL callbacks / initial state (frontend)** — `web/js/config.js` (`loadInitialState`, `HITL_CALLBACKS`).

### Open Interpreter

- **CLI (Codex-based)**: copy `integrations/hooks.json.example` into your OI hooks config and trust it with `/hooks`. The hook script (`integrations/openinterpreter_hook.py`) blocks critical tool calls until approved in the web/TUI. It is fail-open: if the manager is down, OI's native `approval_policy` applies. `PreToolUse` timeout is 900 s, above `approval_timeout_s` (840).
  Hook field names (`tool_name`, `tool_input`, `prompt`) are unverified; if they differ, adjust only `policy.command_text` and the bridge in `server.py`.
- **Classic library** (run inside OI's own venv): `python integrations/oi_classic_runner.py --agent-id my-oi --name "My OI" "your prompt"`. Fail-closed: an unreachable manager rejects execution.

## Layout

```
agent_manager/  config, models, labels, policy, hub, server, client, tui, simulator, hitl_callbacks, sources
integrations/   OI hook + classic runner
web/            vanilla ES modules, no build step
tests/          pytest
```
