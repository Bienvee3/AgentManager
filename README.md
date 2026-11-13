# Agent Manager

Local dashboard for your AI agents: a **3D voxel office** in the browser (isometric, in the style of a corporate open-plan office) where agents walk in when they start working, sit at their desks and type, with status tags, approve/reject bubbles and a log terminal, plus a terminal UI.

For **omp (oh-my-pi)** it follows every project you work on: each active project gets its own room with that project's agents and models, and a door/tab to slide between rooms. Open Interpreter and your own scripts can report to it too. No cost/token metrics anywhere.

## Quick start

**1. Install once** (PowerShell; use `python -m`, `pip.exe` may be blocked on Windows):

```powershell
git clone https://github.com/Bienvee3/AgentManager
cd AgentManager
python -m venv .venv
.venv\Scripts\python -m pip install -r requirements.txt
.venv\Scripts\python -m pip install -e .
```

**2. Launch** (from any directory):

```powershell
<path-to-AgentManager>\.venv\Scripts\python -m agent_manager serve --all
```

On the author's machine: `C:\Users\Bienve\dev\MyProyects\AgentManager\.venv\Scripts\python -m agent_manager serve --all`

**3. Open** `http://127.0.0.1:8765/`. Stop with `Ctrl+C`.

That is all: leave it running and start omp in any project. Within ~10 s that project's room opens and its agents appear at their desks.

**Always on (Windows)**: `.venv\Scripts\python -m agent_manager install-autostart` makes it start minimized every time you log in (`uninstall-autostart` removes it). Then just keep `http://127.0.0.1:8765/` in a tab.

Other ways to launch:
- One project only: `serve --project <path-to-project>` (always has its room, even without an omp session). Inside the project folder you can omit `--project`.
- Port 8765 taken? Add `--port 8766`. Optional terminal UI in another terminal: `.venv\Scripts\python -m agent_manager watch` (`↑/↓` select, `A` approve, `R` reject, `Q` quit).
- One-word launcher: add this to your PowerShell profile (`notepad $PROFILE`) and run `am`:
  ```powershell
  function am { & "C:\Users\Bienve\dev\MyProyects\AgentManager\.venv\Scripts\python" -m agent_manager serve --all @args }
  ```

## How the office works

- **Rooms**: the first active project takes the main office (your avatar `TÚ` sits at the boss desk); every further concurrent project gets its own room. Click a door, a tab in the top bar, or press `←` / `→` to slide between rooms. A project is active while its omp session has had activity in the last 15 min and has not exited; its room closes 60 s after that stops.
- **Desks**: each room holds the main session plus every agent omp offers in that project, looked up like omp does: `<project>\.omp\agents\*.md`, then `~\.omp\agent\agents\*.md` (or `$PI_CODING_AGENT_DIR`), then the bundled `task`, `scout`, `reviewer`, `security-reviewer`, `sonic`. First name wins, so a project agent overrides a user agent. Each agent shows its model, resolved through `modelRoles` in omp's `config.yml` (what `/model` edits) and `task.agentModelOverrides`. Add an agent file and its desk appears within ~10 s.
- **Behaviour** (read-only, from the omp session files): only agents that are doing something are on stage. An agent walks in through the door when it starts working, sits at its own desk (all desks stay visible, empty) and types with a `TRABAJANDO` tag (current tool and intent); it walks out and disappears when it finishes. Errors show `ERROR: RATE LIMIT` for ~2 min; an agent waiting for approval stands and waves with the approve/reject bubble. The main session appears only while omp is working on a prompt. Several instances of one agent (e.g. 3 parallel `task`) share one desk (`+N en paralelo`). Click an agent to see its details in the control panel.
- **No agents are created from sessions.** A running subagent whose definition is not on the roster is ignored; register extra agents through the API or `agents.yaml`. Agents without a project (API/`agents.yaml`/simulator) sit in the main office.
- Only model, stop reason, tool name and intent are read from session files; usage/cost data is ignored. omp's own approvals are **not** intercepted (nothing to hook into); approve/reject buttons work for agents that call the Manager API (below). With two omp windows on the same project, only the newest session is followed.

Fixed agents instead: put an `agents.yaml` (see `agents.example.yaml`) in the current directory, or pass `--config` / set `AGENT_MANAGER_CONFIG`; they appear in the main office next to any omp rooms.

## Demo

```powershell
.venv\Scripts\python -m agent_manager serve --all             # terminal 1
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
agent_manager/  config, models, labels, policy, hub, server, client, tui, simulator, hitl_callbacks, sources, omp_source, autostart
integrations/   Open Interpreter hook + classic runner
web/            vanilla ES modules + 3D world (web/js/world), Three.js vendored in web/vendor, no build step
tests/          pytest
```
