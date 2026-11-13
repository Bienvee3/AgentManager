# Agent Manager

A 3D office in your browser that shows what your AI agents are doing. Each active omp (oh-my-pi) project gets its own room; agents walk in when they start working and leave when they finish. Open Interpreter and your own scripts can report to it too.

## Install (once, Windows PowerShell)

```powershell
git clone https://github.com/Bienvee3/AgentManager
cd AgentManager
python -m venv .venv
.venv\Scripts\python -m pip install -r requirements.txt
.venv\Scripts\python -m pip install -e .
```

Always use `python -m ...`: `pip.exe` can be blocked on Windows.

## Run

```powershell
.venv\Scripts\python -m agent_manager serve --all
```

Open **http://127.0.0.1:8765/**. Leave it running and use omp in any project: its room opens within ~10 s. Stop with `Ctrl+C`.

Run it from anywhere with the full path, e.g. `C:\Users\Bienve\dev\MyProyects\AgentManager\.venv\Scripts\python -m agent_manager serve --all`.

### Start with Windows (optional)

```powershell
.venv\Scripts\python -m agent_manager install-autostart     # remove with: uninstall-autostart
```

### Other commands

| Command | What it does |
|---|---|
| `serve --all` | Every project with a live omp session gets a room (recommended) |
| `serve --project <path>` | One project only, always shown (omit `--project` to use the current folder) |
| `serve --port 8766` | Use another port |
| `watch` | Terminal UI (`↑/↓` select, `A` approve, `R` reject, `Q` quit); add `--url http://127.0.0.1:8766` for another port |
| `simulate --seed 1` | Demo: 4 fake agents asking for approvals (run it while the server is up) |

## What you see

- **Rooms**: the first project takes the main office (you are `TÚ`, at the director's desk); each further project gets its own room. Switch with a door, the tabs at the top, or `←` / `→`. A room opens while the project's omp session is active (activity in the last 15 min) and closes 60 s after it ends.
- **Agents**: every agent omp offers in that project has a desk, with its model. Only agents that are working are on stage: they walk in, sit and type with a status tag, and leave when done. Errors show for ~2 min. An agent waiting for approval stands and waves with an `[APROBAR]` / `[RECHAZAR]` bubble. Click an agent for details.
- **Agent sources**, like omp: `<project>\.omp\agents\*.md`, then `~\.omp\agent\agents\*.md`, then the bundled agents. A project agent overrides a user agent with the same name. Add an agent file and its desk appears within ~10 s.
- **Read-only**: it only reads omp's session files (model, tool name, intent); cost and token data are ignored. omp's own approvals are not intercepted; the approve/reject buttons work for agents that call the Manager API.

Fixed agents instead of omp: put an `agents.yaml` (see `agents.example.yaml`) in the current folder or pass `--config`. They sit in the main office.

## Connect other agents

The server only listens on `127.0.0.1`, and requires JSON `Content-Type` and a local `Origin`, so web pages cannot approve actions through it.

- **Your own scripts**: copy `agent_manager/client.py` (stdlib only):
  ```python
  client = AgentManagerClient("my-agent", name="My Agent"); client.register(); client.start_heartbeat()
  decision = client.request_approval("Deploy", details="...", kind="deploy")   # blocks until decided
  ```
- **Open Interpreter CLI**: copy `integrations/hooks.json.example` into your OI hooks config (fix the path) and trust it with `/hooks`. Fail-open: if the manager is down, OI's own approval policy applies. Hook field names (`tool_name`, `tool_input`, `prompt`) are unverified.
- **Open Interpreter classic**, inside OI's own venv: `python integrations/oi_classic_runner.py --agent-id my-oi --name "My OI" "your prompt"`. Fail-closed: if the manager is down, execution is rejected.
- **Hooks into decisions**: `agent_manager/hitl_callbacks.py` (backend), `web/js/config.js` (frontend). Other agent sources: `agent_manager/sources.py`.

## Development

```powershell
.venv\Scripts\python -m pip install -r requirements-dev.txt
.venv\Scripts\python -m pytest -q
```

`agent_manager/` Python backend · `integrations/` Open Interpreter adapters · `web/` vanilla ES modules, Three.js vendored in `web/vendor`, no build step · `tests/` pytest
