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

MAIN_NAME = "Sesión principal"


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


# ---------------------------------------------------------------- session files


def line(**kw):
    return json.dumps(kw, separators=(",", ":")) + "\n"


def header(cwd):
    return line(type="title", v=1, title="") + line(type="session", version=3, id="s1", cwd=str(cwd))


def init(agent):
    return line(type="session_init", agent=agent, resolvedModel="anthropic/opus")


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


def make_sub(main, name, definition, *events):
    path = main.with_suffix("") / f"{name}.jsonl"
    path.write_text("".join([header("x"), init(definition), *events]), encoding="utf-8")
    return path


def append(path, *lines):
    with path.open("a", encoding="utf-8") as fh:
        fh.write("".join(lines))


def scan(scanner):
    return {u.name: u for u in scanner.scan()}


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
    sub = make_sub(main, "WebUi", "architect", assistant("toolUse", [("read", "Reading the plan")]))
    scanner = SessionScanner(project, omp_home)
    first = scan(scanner)
    assert first[MAIN_NAME].model == "anthropic/sonnet"
    ui = first["WebUi"]
    assert (ui.agent_id, ui.status, ui.task, ui.detail, ui.definition) == (
        "architect", Status.working, "read", "Reading the plan", "architect"
    )
    assert ui.logs == []  # the initial replay must not flood the log

    append(sub, tool_result(), assistant("toolUse", [("edit", "Editing a.py"), ("write", "Writing b.py")]))
    ui = scan(scanner)["WebUi"]
    assert ui.task == "edit, write" and ui.detail == "Writing b.py"
    assert [m for _, m in ui.logs] == ["edit: Editing a.py", "write: Writing b.py"]

    append(sub, tool_result(), assistant("stop", text="All done"))
    ui = scan(scanner)["WebUi"]
    assert (ui.status, ui.detail) == (Status.idle, "Tarea completada")
    assert ("info", "Respuesta: All done") in ui.logs

    append(main, assistant("stop", text="hi"))
    assert scan(scanner)[MAIN_NAME].status == Status.waiting_input


def test_partial_line_is_not_consumed_until_complete(tmp_path, omp_home):
    project = tmp_path / "proj"
    project.mkdir()
    main = make_session(omp_home, project)
    scanner = SessionScanner(project, omp_home)
    scanner.scan()
    full = assistant("toolUse", [("bash", "Running tests")])
    with main.open("a", encoding="utf-8") as fh:
        fh.write(full[:40])
    assert scan(scanner)[MAIN_NAME].status == Status.idle
    append(main, full[40:])
    assert scan(scanner)[MAIN_NAME].detail == "Running tests"


def test_error_exit_and_stale(tmp_path, omp_home):
    project = tmp_path / "proj"
    project.mkdir()
    main = make_session(omp_home, project)
    sub = make_sub(main, "Boom", "task", assistant("error"))
    scanner = SessionScanner(project, omp_home)
    boom = scan(scanner)["Boom"]
    assert (boom.status, boom.error_kind) == (Status.error, "rate_limit")

    append(main, user(), line(type="custom", customType="session_exit", data={"reason": "dispose"}))
    assert scan(scanner)[MAIN_NAME].status == Status.offline

    append(sub, user())
    quiet = time.time() - 600
    os.utime(sub, (quiet, quiet))
    assert scan(scanner)["Boom"].status == Status.paused

    ancient = time.time() - 7200
    os.utime(sub, (ancient, ancient))
    assert scan(scanner)["Boom"].status == Status.offline


def test_long_finished_subagents_are_not_tracked(tmp_path, omp_home):
    project = tmp_path / "proj"
    project.mkdir()
    main = make_session(omp_home, project)
    sub = make_sub(main, "Ancient", "task", assistant("stop", text="done"))
    ancient = time.time() - 7200
    os.utime(sub, (ancient, ancient))
    names = set(scan(SessionScanner(project, omp_home)))
    assert "Ancient" not in names and MAIN_NAME in names


# ---------------------------------------------------------------- watcher -> hub


@pytest.fixture
def world(tmp_path, omp_home):
    project = tmp_path / "proj"
    project.mkdir()
    main = make_session(omp_home, project)
    settings = load_settings(None, str(project))
    hub = Hub(settings, discover_roster(project, omp_home))
    watcher = OmpWatcher(hub, project, home_agent_dir=omp_home)

    def tick():
        asyncio.run(watcher.apply_all(watcher.scanner.scan()))

    return project, main, hub, watcher, tick, omp_home


def test_running_subagent_lights_its_roster_desk_and_creates_nothing(world):
    project, main, hub, _, tick, _ = world
    desks = set(hub.agents)
    make_sub(main, "WebUi", "architect", assistant("toolUse", [("grep", "Searching")]))
    tick()
    assert set(hub.agents) == desks  # no run-* cubicles
    desk = hub.agents["architect"]
    assert (desk.status, desk.task, desk.detail) == (Status.working, "grep", "Searching")
    assert desk.model == "anthropic/opus:high"  # roster model untouched by the instance
    assert hub.agents["scout"].status == Status.idle  # others stay idle
    assert hub.agents[MAIN_AGENT_ID].model == "anthropic/sonnet"
    logs = [e.message for e in hub.logs if e.agent_id == "architect"]
    assert not any(m.startswith("WebUi:") for m in logs)  # replay is silent


def test_parallel_instances_of_one_definition_share_the_desk(world):
    _, main, hub, _, tick, _ = world
    one = make_sub(main, "One", "task", assistant("toolUse", [("read", "Reading A")]))
    make_sub(main, "Two", "task", assistant("toolUse", [("read", "Reading B")]))
    tick()
    assert hub.agents["task"].status == Status.working
    assert hub.agents["task"].detail.endswith("(+1 en paralelo)")

    append(one, assistant("stop", text="x"))
    os.utime(one, (time.time() - 5, time.time() - 5))
    tick()
    assert hub.agents["task"].status == Status.working  # the other instance is still running
    assert "paralelo" not in hub.agents["task"].detail


def test_finished_instance_leaves_desk_idle_and_unknown_definitions_are_ignored(world):
    _, main, hub, _, tick, _ = world
    make_sub(main, "Done", "reviewer", assistant("stop", text="ok"))
    make_sub(main, "Alien", "not-in-roster", assistant("toolUse", [("read", "x")]))
    desks = set(hub.agents)
    tick()
    assert (hub.agents["reviewer"].status, hub.agents["reviewer"].detail) == (Status.idle, "Tarea completada")
    assert set(hub.agents) == desks


def test_desks_reset_when_a_new_session_starts(world):
    project, main, hub, watcher, tick, omp_home = world
    make_sub(main, "Busy", "architect", assistant("toolUse", [("read", "x")]))
    tick()
    assert hub.agents["architect"].status == Status.working
    time.sleep(0.05)
    make_session(omp_home, project, "new")
    tick()
    assert (hub.agents["architect"].status, hub.agents["architect"].detail) == (Status.idle, "Disponible")


def test_error_on_an_instance_shows_on_the_desk(world):
    _, main, hub, _, tick, _ = world
    make_sub(main, "Limited", "debugger-missing", assistant("error"))
    make_sub(main, "Limited2", "task", assistant("error"))
    tick()
    assert (hub.agents["task"].status, hub.agents["task"].error_kind) == (Status.error, "rate_limit")


def test_unchanged_state_does_not_repeat_status_logs(world):
    _, main, hub, _, tick, _ = world
    make_sub(main, "W", "architect", assistant("toolUse", [("grep", "S")]))
    tick()
    before = len(hub.logs)
    tick()
    assert len(hub.logs) == before
