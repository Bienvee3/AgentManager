# Agent Manager

Local server that shows what your AI agents are doing, in:

- a pixel-art web office (`http://127.0.0.1:8765/`): one cubicle per agent, colour-coded status tags, human-in-the-loop (HITL) bubbles with approve/reject, a terminal HUD and a status board;
- a Rich terminal UI (`python -m agent_manager watch`) that approves/rejects with the keyboard.

Agents are never hard-coded. For **omp (oh-my-pi)** they come from the project you point the manager at; other agents (Open Interpreter, your own scripts) register at runtime. No cost/token/consumption metrics are tracked anywhere.

## Install (Windows)

`pip.exe` may be blocked by App Control, so always use `python -m`:

```powershell
cd C:\Users\Bienve\dev\MyProyects\AgentManager
python -m venv .venv
.venv\Scripts\python -m pip install -r requirements-dev.txt
.venv\Scripts\python -m pip install -e .      # makes `agent_manager` importable from any directory
```

## Use it in any project (omp)

```powershell
# from anywhere; the manager shows THAT project's agents
C:\Users\Bienve\dev\MyProyects\AgentManager\.venv\Scripts\python -m agent_manager serve --project C:\path\to\project
# or cd into the project and omit --project
```

What you get for the project:

- **Roster** (idle desks): the agent definitions omp would offer there, discovered like omp does: nearest `<project>\.omp\agents\*.md`, then `~\.omp\agent\agents\*.md` (or `$PI_CODING_AGENT_DIR`), then the bundled agents (`task`, `scout`, `reviewer`, `security-reviewer`, `sonic`). First name wins, so a project agent overrides a user agent. Each desk shows its model, resolved through `modelRoles` in `config.yml` (the same mapping `/model` edits) and `task.agentModelOverrides`.
- **Live status** (read-only): the manager tails the project's newest omp session (`~\.omp\agent\sessions\<project>\*.jsonl` and the per-subagent files). The main session shows as `Sesión principal`; every running subagent gets its own cubicle (`run-<name>`) with the current tool and intent, `TRABAJANDO`, `INACTIVO` when finished, `ERROR: RATE LIMIT` on provider limits. Only structural fields are read (model, stop reason, tool name, intent); usage/cost data in those files is ignored.
- Sessions untouched for more than 1 h are shown offline / not listed. If you run two omp windows in the same project, only the newest session is followed.

Run one manager per project with different ports (`--port 8766`). omp's own approval flow is not intercepted: HITL buttons apply to agents that call the Manager API (see below).

An `agents.yaml` (in the current directory, `--config` or `AGENT_MANAGER_CONFIG`) switches to fixed, config-defined agents; the omp live watcher then only runs if you also pass `--project`.

## Other commands

```powershell
.venv\Scripts\python -m agent_manager watch [--url http://127.0.0.1:8765]
.venv\Scripts\python -m agent_manager simulate [--url ...] [--seed 1]   # demo agents (registered at runtime)
.venv\Scripts\python -m pytest -q
```

The server listens on `127.0.0.1` only. POSTs require `Content-Type: application/json` and the WebSocket checks `Origin`, so a web page cannot approve actions through localhost.

## Integration points

1. **Agents** — omp: automatic (above). Others: `agent_manager/sources.py::load_agents` (swap the source), `agents.yaml`, or register at runtime with `agent_manager/client.py` (stdlib-only, copy it into any venv):
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
agent_manager/  config, models, labels, policy, hub, server, client, tui, simulator, hitl_callbacks, sources, omp_source
integrations/   OI hook + classic runner
web/            vanilla ES modules, no build step
tests/          pytest
```
