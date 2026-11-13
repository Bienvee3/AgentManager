# AGENTS.md — Agent Manager

Spec: `../AGENT_MANAGER_PLAN.md`.

## Stack
Python 3.11, FastAPI + uvicorn (hub in memory, asyncio), Rich TUI, vanilla ES-module web UI with vendored Three.js (no npm/build). `client.py` and `integrations/*` are stdlib-only and must not import the package.

## Commands (always `python -m`; `pip.exe` is blocked on this machine)
- Install: `.venv\Scripts\python -m pip install -r requirements-dev.txt`
- Tests: `.venv\Scripts\python -m pytest -q`
- Serve: `.venv\Scripts\python -m agent_manager serve`

## Conventions
- Code, comments, README in English; UI/TUI strings in Spanish (spec).
- `# INTEGRATION POINT:` comments mark the places users plug in agents/callbacks.
- Never add cost/token/budget metrics anywhere (UI, TUI, data model).
- UI text from agents is rendered with `textContent` only.
- `agent_manager/__init__.py` stays empty.
- Branch: `main`. Conventional commits.
