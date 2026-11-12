# Current status

- Branch: `main`. Plan `../AGENT_MANAGER_PLAN.md` implemented end to end (repo dir is `AgentManager`, not `agent-manager` as the plan text says).
- Post-plan feature: per-project omp integration (`agent_manager/omp_source.py`): roster from project/user/bundled agent definitions with models resolved via `modelRoles`, plus a read-only live watcher of the project's omp session files. `serve --project DIR`; without `agents.yaml` the example demo agents are no longer loaded (only `simulate` creates them). `AgentState.model` added; shown on the web nameplate and in the TUI panel.
- Tests: `Tests run: 42, Failures: 0, Errors: 0 — BUILD SUCCESS` (`.venv\Scripts\python -m pytest -q`).
- Smoke verified (2026-11-12): `serve` + `simulate` + web UI, TUI reject/quit, OI hook deny; omp live view against this project (main session working, 3 finished subagents, models resolved) and against `dev/Java/SportsLeagueManagement` (different roster/sessions).
- Not exercised: simulator Ctrl+C shutdown, `oi_classic_runner.py` against real Open Interpreter, OI CLI hook field names, project-level omp `config.yml` overlay (file name assumed), multiple concurrent omp sessions in one project (only newest followed).
- Next: wire non-omp agents (README "Integration points"); push only with explicit authorization.
