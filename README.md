# Agent Manager

Local dashboard for your AI agents: a pixel-art office in the browser (one cubicle per agent, status tags, approve/reject bubbles, log terminal) plus a terminal UI.

For **omp (oh-my-pi)** it shows the agents of whichever project you point it at, with their models and live status. Open Interpreter and your own scripts can report to it too. No cost/token metrics anywhere.

## Quick start

**1. Install once** (PowerShell; use `python -m`, `pip.exe` may be blocked on Windows):

```powershell
git clone https://github.com/Bienvee3/AgentManager
cd AgentManager
python -m venv .venv
.venv\Scripts\python -m pip install -r requirements.txt
.venv\Scripts\python -m pip install -e .
```

**2. Launch it for a project** (from any directory):

```powershell
<path-to-AgentManager>\.venv\Scripts\python -m agent_manager serve --project <path-to-your-project> --port 8766
```

Example for the author's machine:

```powershell
C:\Users\Bienve\dev\MyProyects\AgentManager\.venv\Scripts\python -m agent_manager serve --project C:\Users\Bienve\dev\Java\SportsLeagueManagement --port 8766
```

**3. Open** `http://127.0.0.1:8766/`. Stop with `Ctrl+C`.

Tips:
- Already inside the project folder? Omit `--project`; the current directory is used.
- One project per manager. To watch several at once, use a different `--port` for each.
- Add `--port` only if 8765 (the default) is taken.
- Optional terminal UI, in another terminal: `.venv\Scripts\python -m agent_manager watch --url http://127.0.0.1:8766` (`↑/↓` select, `A` approve, `R` reject, `Q` quit).
- Want a one-word launcher? Add this to your PowerShell profile (`notepad $PROFILE`), then run `am` inside any project:
  ```powershell
  function am { & "C:\Users\Bienve\dev\MyProyects\AgentManager\.venv\Scripts\python" -m agent_manager serve --project (Get-Location) @args }
  ```

## What you see for a project (omp)

- **Idle desks**: the agents omp offers in that project. Looked up like omp does: `<project>\.omp\agents\*.md`, then `~\.omp\agent\agents\*.md` (or `$PI_CODING_AGENT_DIR`), then the bundled `task`, `scout`, `reviewer`, `security-reviewer`, `sonic`. First name wins, so a project agent overrides a user agent. Each desk shows its model, resolved through `modelRoles` in omp's `config.yml` (what `/model` edits) and `task.agentModelOverrides`.
- **Live status** (read-only): the manager follows the project's newest omp session under `~\.omp\agent\sessions\`. `Sesión principal` is the main agent; every running subagent gets its own cubicle (`run-<name>`) showing the current tool and intent. Only model, stop reason, tool name and intent are read; usage/cost data in those files is ignored.
- Sessions untouched for more than 1 h show as offline. With two omp windows on the same project, only the newest session is followed.
- omp's own approvals are **not** intercepted (nothing to hook into); approve/reject buttons work for agents that call the Manager API (below).

Fixed agents instead: put an `agents.yaml` (see `agents.example.yaml`) in the current directory, or pass `--config` / set `AGENT_MANAGER_CONFIG`. Then agents come from that file, and the omp live view runs only if you also pass `--project`.

## Demo

```powershell
.venv\Scripts\python -m agent_manager serve --port 8765      # terminal 1
.venv\Scripts\python -m agent_manager simulate --seed 1      # terminal 2: 4 fake agents asking for approvals
```

## Connecting other agents

The server listens on `127.0.0.1` only. POSTs require `Content-Type: application/json` and the WebSocket checks `Origin`, so a web page cannot approve actions through localhost.

1. **Your own scripts**: `agent_manager/client.py` (stdlib-only, copy it anywhere):
   ```python
   client = AgentManagerClient("my-agent", name="My Agent"); client.register(); client.start_heartbeat()
   decision = client.request_approval("Deploy", details="...", kind="deploy")   # blocks until approved/rejected
   ```
2. **Backend HITL callbacks**: `agent_manager/hitl_callbacks.py` (`on_approved` / `on_rejected`; the latter also on expiry).
3. **Frontend hooks / initial state**: `web/js/config.js` (`loadInitialState`, `HITL_CALLBACKS`).
4. **Other agent sources**: swap `agent_manager/sources.py::load_agents`.

### Open Interpreter

- **CLI (Codex-based)**: copy `integrations/hooks.json.example` into your OI hooks config (adjust the path) and trust it with `/hooks`. Critical tool calls block until approved in the web/TUI. Fail-open: if the manager is down, OI's native `approval_policy` applies. Hook field names (`tool_name`, `tool_input`, `prompt`) are unverified; if they differ, adjust `policy.command_text` and the bridge in `server.py`.
- **Classic library** (run in OI's own venv): `python integrations/oi_classic_runner.py --agent-id my-oi --name "My OI" "your prompt"`. Fail-closed: an unreachable manager rejects execution.

## Development

```powershell
.venv\Scripts\python -m pip install -r requirements-dev.txt
.venv\Scripts\python -m pytest -q
```

```
agent_manager/  config, models, labels, policy, hub, server, client, tui, simulator, hitl_callbacks, sources, omp_source
integrations/   Open Interpreter hook + classic runner
web/            vanilla ES modules, no build step
tests/          pytest
```
