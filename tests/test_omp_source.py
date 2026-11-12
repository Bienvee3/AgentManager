import asyncio
import json
import os
import time

import pytest

from agent_manager.config import load_settings
from agent_manager.hub import Hub
from agent_manager.models import Status
from agent_manager.omp_source import (
    MAIN_AGENT_ID,
    OmpWatcher,
    SessionScanner,
    discover_roster,
    find_sessions_dir,
)
from agent_manager.sources import load_agents


def agent_md(name, model=None, desc="does things"):
    meta = f"---\nname: {name}\ndescription: {desc}\n"
    if model:
        meta += f"model:\n  - \"{model}\"\n"
    return meta + "---\n\nPrompt body\n"


@pytest.fixture
def omp_home(tmp_path):
    home = tmp_path / "omp-agent"
    (home / "agents").mkdir(parents=True)
    (home / "agents" / "architect.md").write_text(agent_md("architect", "@plan"), encoding="utf-8")
    (home / "agents" / "reviewer.md").write_text(agent_md("reviewer", "@missing"), encoding="utf-8")
    (home / "agents" / "broken.md").write_text("no frontmatter here", encoding="utf-8")
    (home / "config.yml").write_text(
        "modelRoles:\n  default: anthropic/sonnet\n  plan: anthropic/opus:high\n"
        "task:\n  agentModelOverrides:\n    sonic: '@plan'\n",
        encoding="utf-8",
    )
    return home


def by_id(agents):
    return {a.id: a for a in agents}


# ---------------------------------------------------------------- roster


def test_roster_resolves_models_through_roles(tmp_path, omp_home):
    agents = by_id(discover_roster(tmp_path / "proj", omp_home))
    assert agents[MAIN_AGENT_ID].model == "anthropic/sonnet"
    assert agents["architect"].model == "anthropic/opus:high"
    assert agents["sonic"].model == "anthropic/opus:high"  # settings override on a bundled agent
    assert agents["scout"].model == "anthropic/sonnet"  # no model -> parent's default
    assert agents["reviewer"].model == "anthropic/sonnet"  # unknown role alias -> default
    assert "broken" not in agents


def test_project_agents_differ_per_project_and_override_user(tmp_path, omp_home):
    a, b = tmp_path / "a", tmp_path / "b"
    (a / ".omp" / "agents").mkdir(parents=True)
    (a / ".omp" / "agents" / "architect.md").write_text(agent_md("architect", "x/y", "project one"), encoding="utf-8")
    (a / ".omp" / "agents" / "db-expert.md").write_text(agent_md("db-expert"), encoding="utf-8")
    b.mkdir()
    roster_a, roster_b = by_id(discover_roster(a, omp_home)), by_id(discover_roster(b, omp_home))
    assert "db-expert" in roster_a and "db-expert" not in roster_b
    assert roster_a["architect"].model == "x/y" and roster_a["architect"].role == "project"
    assert roster_b["architect"].model == "anthropic/opus:high" and roster_b["architect"].role == "user"


def test_project_agents_found_from_subdirectory(tmp_path, omp_home):
    root = tmp_path / "repo"
    (root / ".omp" / "agents").mkdir(parents=True)
    (root / ".omp" / "agents" / "only-here.md").write_text(agent_md("only-here"), encoding="utf-8")
    (root / "sub" / "dir").mkdir(parents=True)
    assert "only-here" in by_id(discover_roster(root / "sub" / "dir", omp_home))


# ---------------------------------------------------------------- config / sources


def test_without_agents_yaml_uses_project_roster_not_demo_agents(tmp_path, monkeypatch, omp_home):
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("AGENT_MANAGER_CONFIG", raising=False)
    monkeypatch.setenv("PI_CODING_AGENT_DIR", str(omp_home))
    settings = load_settings(None)
    assert settings.agents_source == "omp" and settings.project == tmp_path.resolve()
    ids = {a.id for a in load_agents(settings)}
    assert "architect" in ids and "refactor-bot" not in ids


def test_explicit_config_keeps_yaml_agents_and_no_watcher(settings):
    assert settings.agents_source == "config" and settings.project is None
    assert [a.id for a in load_agents(settings)] == ["alpha", "beta"]


def test_missing_project_dir_exits(tmp_path):
    with pytest.raises(SystemExit):
        load_settings(None, str(tmp_path / "nope"))


# ---------------------------------------------------------------- sessions


def line(**kw):
    return json.dumps(kw, separators=(",", ":")) + "\n"


def header(cwd):
    return line(type="title", v=1, title="") + line(type="session", version=3, id="s1", cwd=str(cwd))


def assistant(stop, calls=(), text=""):
    content = [{"type": "toolCall", "id": f"t{i}", "name": n, "arguments": {"i": intent}, "intent": intent}
               for i, (n, intent) in enumerate(calls)]
    if text:
        content.append({"type": "text", "text": text})
    msg = {"role": "assistant", "content": content, "stopReason": stop}
    if stop == "error":
        msg["errorMessage"] = "Cloud API error (429): quota"
    return line(type="message", id="m", parentId=None, timestamp="2026-01-01T00:00:00Z", message=msg)


def tool_result():
    return line(type="message", id="r", parentId=None, timestamp="x", message={"role": "toolResult", "content": []})


def user():
    return line(type="message", id="u", parentId=None, timestamp="x", message={"role": "user", "content": []})


def make_session(home, project, name="2026_abc"):
    sdir = home / "sessions" / "-custom-slug"
    sdir.mkdir(parents=True, exist_ok=True)
    main = sdir / f"{name}.jsonl"
    main.write_text(header(project) + line(type="model_change", model="anthropic/sonnet"), encoding="utf-8")
    (sdir / name).mkdir(exist_ok=True)
    return main


def append(path, *lines):
    with path.open("a", encoding="utf-8") as fh:
        fh.write("".join(lines))


def test_sessions_dir_is_found_by_header_cwd_not_by_name(tmp_path, omp_home):
    project = tmp_path / "proj"
    project.mkdir()
    make_session(omp_home, project)
    other = tmp_path / "other"
    other.mkdir()
    assert find_sessions_dir(project, omp_home) == omp_home / "sessions" / "-custom-slug"
    assert find_sessions_dir(other, omp_home) is None


def test_scanner_tracks_main_and_subagents_incrementally(tmp_path, omp_home):
    project = tmp_path / "proj"
    project.mkdir()
    main = make_session(omp_home, project)
    sub = main.with_suffix("") / "WebUi.jsonl"
    sub.write_text(
        header(project)
        + line(type="session_init", agent="architect", resolvedModel="anthropic/opus")
        + assistant("toolUse", [("read", "Reading the plan")]),
        encoding="utf-8",
    )
    scanner = SessionScanner(project, omp_home)
    first = {u.agent_id: u for u in scanner.scan()}
    assert first[MAIN_AGENT_ID].model == "anthropic/sonnet"
    ui = first["run-webui"]
    assert (ui.status, ui.task, ui.detail, ui.role, ui.model) == (
        Status.working, "read", "Reading the plan", "architect", "anthropic/opus"
    )
    assert ui.logs == []  # the initial replay must not flood the log

    append(sub, tool_result(), assistant("toolUse", [("edit", "Editing a.py"), ("write", "Writing b.py")]))
    ui = {u.agent_id: u for u in scanner.scan()}["run-webui"]
    assert ui.task == "edit, write" and ui.detail == "Writing b.py"
    assert [m for _, m in ui.logs] == ["edit: Editing a.py", "write: Writing b.py"]

    append(sub, tool_result(), assistant("stop", text="All done"))
    ui = {u.agent_id: u for u in scanner.scan()}["run-webui"]
    assert (ui.status, ui.detail) == (Status.idle, "Tarea completada")
    assert ("info", "Respuesta: All done") in ui.logs

    append(main, assistant("stop", text="hi"))
    assert {u.agent_id: u for u in scanner.scan()}[MAIN_AGENT_ID].status == Status.waiting_input


def test_partial_line_is_not_consumed_until_complete(tmp_path, omp_home):
    project = tmp_path / "proj"
    project.mkdir()
    main = make_session(omp_home, project)
    scanner = SessionScanner(project, omp_home)
    scanner.scan()
    full = assistant("toolUse", [("bash", "Running tests")])
    with main.open("a", encoding="utf-8") as fh:
        fh.write(full[:40])
    assert {u.agent_id: u for u in scanner.scan()}[MAIN_AGENT_ID].status == Status.idle
    append(main, full[40:])
    assert {u.agent_id: u for u in scanner.scan()}[MAIN_AGENT_ID].detail == "Running tests"


def test_error_exit_and_stale(tmp_path, omp_home):
    project = tmp_path / "proj"
    project.mkdir()
    main = make_session(omp_home, project)
    sub = main.with_suffix("") / "Boom.jsonl"
    sub.write_text(header(project) + assistant("error"), encoding="utf-8")
    scanner = SessionScanner(project, omp_home)
    boom = {u.agent_id: u for u in scanner.scan()}["run-boom"]
    assert (boom.status, boom.error_kind) == (Status.error, "rate_limit")

    append(main, user(), line(type="custom", customType="session_exit", data={"reason": "dispose"}))
    assert {u.agent_id: u for u in scanner.scan()}[MAIN_AGENT_ID].status == Status.offline

    append(sub, user())
    quiet = time.time() - 600
    os.utime(sub, (quiet, quiet))
    assert {u.agent_id: u for u in scanner.scan()}["run-boom"].status == Status.paused

    ancient = time.time() - 7200
    os.utime(sub, (ancient, ancient))
    assert {u.agent_id: u for u in scanner.scan()}["run-boom"].status == Status.offline


def test_long_finished_subagents_are_not_listed(tmp_path, omp_home):
    project = tmp_path / "proj"
    project.mkdir()
    main = make_session(omp_home, project)
    sub = main.with_suffix("") / "Ancient.jsonl"
    sub.write_text(header(project) + assistant("stop", text="done"), encoding="utf-8")
    ancient = time.time() - 7200
    os.utime(sub, (ancient, ancient))
    ids = {u.agent_id for u in SessionScanner(project, omp_home).scan()}
    assert "run-ancient" not in ids and MAIN_AGENT_ID in ids


def test_new_session_retires_previous_subagents(tmp_path, omp_home):
    project = tmp_path / "proj"
    project.mkdir()
    old = make_session(omp_home, project, "old")
    (old.with_suffix("") / "Gone.jsonl").write_text(header(project) + assistant("toolUse", [("read", "x")]), encoding="utf-8")
    scanner = SessionScanner(project, omp_home)
    scanner.scan()
    time.sleep(0.05)
    make_session(omp_home, project, "new")
    updates = {u.agent_id: u for u in scanner.scan()}
    assert updates["run-gone"].status == Status.offline
    assert updates["run-gone"].detail == "Sesión anterior"


def test_watcher_pushes_new_instances_and_status_to_hub(tmp_path, omp_home):
    project = tmp_path / "proj"
    project.mkdir()
    main = make_session(omp_home, project)
    (main.with_suffix("") / "Worker.jsonl").write_text(
        header(project) + line(type="session_init", agent="task") + assistant("toolUse", [("grep", "Searching")]),
        encoding="utf-8",
    )
    settings = load_settings(None, str(project))
    hub = Hub(settings, discover_roster(project, omp_home))
    watcher = OmpWatcher(hub, project, home_agent_dir=omp_home)

    async def go():
        for update in watcher.scanner.scan():
            await watcher.apply(update)
        before = len(hub.logs)
        for update in watcher.scanner.scan():  # unchanged -> no duplicate status logs
            await watcher.apply(update)
        return before, len(hub.logs)

    before, after = asyncio.run(go())
    assert before == after
    worker = hub.agents["run-worker"]
    assert worker.source == "runtime" and worker.role == "task"
    assert (worker.status, worker.task, worker.detail) == (Status.working, "grep", "Searching")
    assert hub.agents[MAIN_AGENT_ID].model == "anthropic/sonnet"
    assert hub.agents["architect"].status == Status.idle  # roster desk untouched
