import asyncio
import json
import os
import time

import pytest

from agent_manager.config import load_settings
from agent_manager.hub import Hub
from agent_manager.models import Status
from agent_manager.omp_source import (
    CLOSE_GRACE_S,
    DISCOVERY_INTERVAL_S,
    ProjectsWatcher,
    SessionScanner,
    agent_id_for,
    discover_roster,
    find_sessions_dir,
    main_agent_id,
    project_key,
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


def roster(project, home):
    return by_id(discover_roster(project, project_key(project), home))


# ---------------------------------------------------------------- roster


def test_roster_resolves_models_through_roles_and_namespaces_ids(tmp_path, omp_home):
    project = tmp_path / "proj"
    key = project_key(project)
    agents = roster(project, omp_home)
    assert agents[main_agent_id(key)].model == "anthropic/sonnet"
    assert agents[agent_id_for(key, "architect")].model == "anthropic/opus:high"
    assert agents[agent_id_for(key, "sonic")].model == "anthropic/opus:high"  # settings override on a bundled agent
    assert agents[agent_id_for(key, "scout")].model == "anthropic/sonnet"  # no model -> parent's default
    assert agents[agent_id_for(key, "reviewer")].model == "anthropic/sonnet"  # unknown role alias -> default
    assert agent_id_for(key, "broken") not in agents
    assert all(a.project == key and a.id.startswith(f"{key}--") for a in agents.values())


def test_same_agent_names_in_two_projects_do_not_collide(tmp_path, omp_home):
    a, b = tmp_path / "a", tmp_path / "b"
    assert set(roster(a, omp_home)).isdisjoint(roster(b, omp_home))
    assert project_key(a) != project_key(b)


def test_project_agents_differ_per_project_and_override_user(tmp_path, omp_home):
    a, b = tmp_path / "a", tmp_path / "b"
    (a / ".omp" / "agents").mkdir(parents=True)
    (a / ".omp" / "agents" / "architect.md").write_text(agent_md("architect", "x/y", "project one"), encoding="utf-8")
    (a / ".omp" / "agents" / "db-expert.md").write_text(agent_md("db-expert"), encoding="utf-8")
    b.mkdir()
    ka, kb = project_key(a), project_key(b)
    roster_a, roster_b = roster(a, omp_home), roster(b, omp_home)
    assert agent_id_for(ka, "db-expert") in roster_a and agent_id_for(kb, "db-expert") not in roster_b
    assert roster_a[agent_id_for(ka, "architect")].model == "x/y"
    assert roster_a[agent_id_for(ka, "architect")].role == "project"
    assert roster_b[agent_id_for(kb, "architect")].model == "anthropic/opus:high"
    assert roster_b[agent_id_for(kb, "architect")].role == "user"


def test_project_agents_found_from_subdirectory(tmp_path, omp_home):
    root = tmp_path / "repo"
    (root / ".omp" / "agents").mkdir(parents=True)
    (root / ".omp" / "agents" / "only-here.md").write_text(agent_md("only-here"), encoding="utf-8")
    (root / "sub" / "dir").mkdir(parents=True)
    sub = root / "sub" / "dir"
    assert agent_id_for(project_key(sub), "only-here") in roster(sub, omp_home)


# ---------------------------------------------------------------- config / sources


def test_without_agents_yaml_pins_cwd_and_loads_no_demo_agents(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("AGENT_MANAGER_CONFIG", raising=False)
    settings = load_settings(None)
    assert settings.agents_source == "omp" and settings.project == tmp_path.resolve()
    assert not settings.discover_all
    assert load_agents(settings) == []  # rosters come from the watcher, never from the demo example


def test_all_flag_watches_every_project_without_pinning_cwd(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("AGENT_MANAGER_CONFIG", raising=False)
    settings = load_settings(None, None, True)
    assert settings.project is None and settings.discover_all
    assert settings.agents_source == "omp"


def test_explicit_config_keeps_yaml_agents_and_no_watcher(settings):
    assert settings.agents_source == "config" and settings.project is None and not settings.discover_all
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


def exit_line():
    return line(type="custom", customType="session_exit", data={"reason": "dispose"})


def make_session(home, project, name="2026_abc", dirname="-custom-slug"):
    sdir = home / "sessions" / dirname
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
    assert (ui.status, ui.task, ui.detail, ui.definition) == (Status.working, "read", "Reading the plan", "architect")
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
    main_state = scan(scanner)[MAIN_NAME]
    assert (main_state.status, main_state.detail) == (Status.idle, "Esperando tu input")  # off stage until the next prompt


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

    append(main, user(), exit_line())
    assert scan(scanner)[MAIN_NAME].status == Status.offline

    append(sub, user())
    quiet = time.time() - 600
    os.utime(sub, (quiet, quiet))
    assert scan(scanner)["Boom"].status == Status.paused

    ancient = time.time() - 7200
    os.utime(sub, (ancient, ancient))
    assert scan(scanner)["Boom"].status == Status.offline


def test_a_failed_run_stops_showing_its_error_after_a_while(tmp_path, omp_home):
    project = tmp_path / "proj"
    project.mkdir()
    main = make_session(omp_home, project)
    sub = make_sub(main, "Failed", "task", assistant("error"))
    scanner = SessionScanner(project, omp_home)
    assert scan(scanner)["Failed"].status == Status.error
    stale = time.time() - 200
    os.utime(sub, (stale, stale))
    failed = scan(scanner)["Failed"]
    assert (failed.status, failed.error_kind) == (Status.idle, None)


def test_long_finished_subagents_are_not_tracked(tmp_path, omp_home):
    project = tmp_path / "proj"
    project.mkdir()
    main = make_session(omp_home, project)
    sub = make_sub(main, "Ancient", "task", assistant("stop", text="done"))
    ancient = time.time() - 7200
    os.utime(sub, (ancient, ancient))
    names = set(scan(SessionScanner(project, omp_home)))
    assert "Ancient" not in names and MAIN_NAME in names


# ---------------------------------------------------------------- watcher -> hub: one project


@pytest.fixture
def world(tmp_path, omp_home, settings):
    project = tmp_path / "proj"
    project.mkdir()
    main = make_session(omp_home, project)
    hub = Hub(settings, [])
    watcher = ProjectsWatcher(hub, [project], False, home_agent_dir=omp_home)
    key = project_key(project.resolve())

    def tick():
        asyncio.run(watcher.tick())

    return main, hub, tick, key, omp_home, project


def desk(hub, key, name):
    return hub.agents[agent_id_for(key, name)]


def test_running_subagent_lights_its_roster_desk_and_creates_nothing(world):
    main, hub, tick, key, _, _ = world
    tick()
    desks = set(hub.agents)
    make_sub(main, "WebUi", "architect", assistant("toolUse", [("grep", "Searching")]))
    tick()
    assert set(hub.agents) == desks  # no run-* cubicles
    architect = desk(hub, key, "architect")
    assert (architect.status, architect.task, architect.detail) == (Status.working, "grep", "Searching")
    assert architect.model == "anthropic/opus:high"  # roster model untouched by the instance
    assert desk(hub, key, "scout").status == Status.idle  # others stay idle
    assert hub.agents[main_agent_id(key)].model == "anthropic/sonnet"
    logs = [e.message for e in hub.logs if e.agent_id == architect.id]
    assert not any(m.startswith("WebUi:") for m in logs)  # replay is silent


def test_parallel_instances_of_one_definition_share_the_desk(world):
    main, hub, tick, key, _, _ = world
    one = make_sub(main, "One", "task", assistant("toolUse", [("read", "Reading A")]))
    make_sub(main, "Two", "task", assistant("toolUse", [("read", "Reading B")]))
    tick()
    assert desk(hub, key, "task").status == Status.working
    assert desk(hub, key, "task").detail.endswith("(+1 en paralelo)")

    append(one, assistant("stop", text="x"))
    os.utime(one, (time.time() - 5, time.time() - 5))
    tick()
    assert desk(hub, key, "task").status == Status.working  # the other instance is still running
    assert "paralelo" not in desk(hub, key, "task").detail


def test_finished_instance_leaves_desk_idle_and_unknown_definitions_are_ignored(world):
    main, hub, tick, key, _, _ = world
    tick()
    make_sub(main, "Done", "reviewer", assistant("stop", text="ok"))
    make_sub(main, "Alien", "not-in-roster", assistant("toolUse", [("read", "x")]))
    desks = set(hub.agents)
    tick()
    reviewer = desk(hub, key, "reviewer")
    assert (reviewer.status, reviewer.detail) == (Status.idle, "Tarea completada")
    assert set(hub.agents) == desks


def test_desks_reset_when_a_new_session_starts(world):
    main, hub, tick, key, omp_home, project = world
    make_sub(main, "Busy", "architect", assistant("toolUse", [("read", "x")]))
    tick()
    assert desk(hub, key, "architect").status == Status.working
    time.sleep(0.05)
    make_session(omp_home, project, "new")
    tick()
    assert (desk(hub, key, "architect").status, desk(hub, key, "architect").detail) == (Status.idle, "Disponible")


def test_error_on_an_instance_shows_on_the_desk(world):
    main, hub, tick, key, _, _ = world
    make_sub(main, "Limited", "task", assistant("error"))
    tick()
    task = desk(hub, key, "task")
    assert (task.status, task.error_kind) == (Status.error, "rate_limit")


def test_unchanged_state_does_not_repeat_status_logs(world):
    main, hub, tick, key, _, _ = world
    make_sub(main, "W", "architect", assistant("toolUse", [("grep", "S")]))
    tick()
    before = len(hub.logs)
    tick()
    assert len(hub.logs) == before


def test_pinned_project_without_sessions_has_full_roster_and_never_closes(tmp_path, omp_home, settings):
    project = tmp_path / "quiet"
    project.mkdir()
    hub = Hub(settings, [])
    now = [1_000.0]
    watcher = ProjectsWatcher(hub, [project], False, home_agent_dir=omp_home, clock=lambda: now[0])

    async def go():
        await watcher.tick()
        now[0] += 100_000
        await watcher.tick()

    asyncio.run(go())
    key = project_key(project.resolve())
    assert hub.projects[key].room == 0
    assert hub.agents[main_agent_id(key)].status == Status.offline
    assert desk(hub, key, "architect").status == Status.idle


# ---------------------------------------------------------------- watcher -> hub: many projects


class Clock:
    def __init__(self):
        self.now = time.time()

    def __call__(self):
        return self.now


def drain(queue):
    events = []
    while not queue.empty():
        events.append(queue.get_nowait())
    return events


def test_two_active_projects_get_two_rooms_and_only_their_own_desks_light(tmp_path, omp_home, settings):
    a, b = tmp_path / "a", tmp_path / "b"
    a.mkdir(), b.mkdir()
    make_session(omp_home, a, dirname="-a")
    main_b = make_session(omp_home, b, dirname="-b")
    make_sub(main_b, "Worker", "architect", assistant("toolUse", [("grep", "Searching")]))
    hub = Hub(settings, [])
    watcher = ProjectsWatcher(hub, [], True, home_agent_dir=omp_home, clock=Clock())
    asyncio.run(watcher.tick())

    ka, kb = project_key(a.resolve()), project_key(b.resolve())
    assert {p.id: p.room for p in hub.projects.values()} == {ka: 0, kb: 1}  # sorted by path: a, b
    assert all(x.project in (ka, kb) for x in hub.agents.values())
    assert desk(hub, kb, "architect").status == Status.working
    assert desk(hub, ka, "architect").status == Status.idle
    assert {x.id for x in hub.agents.values() if x.id.endswith("--main")} == {main_agent_id(ka), main_agent_id(kb)}


def test_exited_or_stale_sessions_do_not_open_rooms(tmp_path, omp_home, settings):
    done, stale = tmp_path / "done", tmp_path / "stale"
    done.mkdir(), stale.mkdir()
    exited = make_session(omp_home, done, dirname="-done")
    append(exited, user(), exit_line())
    old = make_session(omp_home, stale, dirname="-stale")
    ancient = time.time() - 3600
    os.utime(old, (ancient, ancient))
    os.utime(old.with_suffix(""), (ancient, ancient))
    hub = Hub(settings, [])
    asyncio.run(ProjectsWatcher(hub, [], True, home_agent_dir=omp_home, clock=Clock()).tick())
    assert hub.projects == {} and hub.agents == {}


def test_room_closes_after_grace_and_its_room_number_is_reused(tmp_path, omp_home, settings):
    a, b, c = tmp_path / "a", tmp_path / "b", tmp_path / "c"
    for p in (a, b, c):
        p.mkdir()
    main_a = make_session(omp_home, a, dirname="-a")
    make_session(omp_home, b, dirname="-b")
    clock = Clock()
    hub = Hub(settings, [])
    watcher = ProjectsWatcher(hub, [], True, home_agent_dir=omp_home, clock=clock)
    ka, kb, kc = (project_key(p.resolve()) for p in (a, b, c))

    async def go():
        queue = await hub.subscribe()
        await watcher.tick()
        assert {p.id: p.room for p in hub.projects.values()} == {ka: 0, kb: 1}
        drain(queue)

        append(main_a, user(), exit_line())
        clock.now += DISCOVERY_INTERVAL_S
        await watcher.tick()  # noticed as inactive; grace starts
        assert ka in hub.projects
        clock.now += CLOSE_GRACE_S - 1
        await watcher.tick()
        assert ka in hub.projects  # still inside the grace period
        assert any(x.project == ka for x in hub.agents.values())

        clock.now += 1
        await watcher.tick()
        assert ka not in hub.projects and kb in hub.projects
        assert not any(x.project == ka for x in hub.agents.values())
        kinds = [e["type"] for e in drain(queue)]
        assert "project_removed" in kinds and kinds.count("agent_removed") > 5

        make_session(omp_home, c, dirname="-c")
        clock.now += DISCOVERY_INTERVAL_S
        await watcher.tick()
        assert hub.projects[kc].room == 0  # the freed room number is reused

    asyncio.run(go())


def test_roster_changes_are_picked_up_while_the_room_is_open(tmp_path, omp_home, settings):
    project = tmp_path / "proj"
    project.mkdir()
    clock = Clock()
    hub = Hub(settings, [])
    watcher = ProjectsWatcher(hub, [project], False, home_agent_dir=omp_home, clock=clock)
    key = project_key(project.resolve())
    new_agent = project / ".omp" / "agents" / "new-one.md"

    async def go():
        await watcher.tick()
        assert agent_id_for(key, "new-one") not in hub.agents
        new_agent.parent.mkdir(parents=True)
        new_agent.write_text(agent_md("new-one"), encoding="utf-8")
        clock.now += DISCOVERY_INTERVAL_S
        await watcher.tick()
        assert agent_id_for(key, "new-one") in hub.agents
        new_agent.unlink()
        clock.now += DISCOVERY_INTERVAL_S
        await watcher.tick()
        assert agent_id_for(key, "new-one") not in hub.agents

    asyncio.run(go())


# ---------------------------------------------------------------- hub


def test_removing_an_agent_expires_its_pending_approvals(settings):
    from agent_manager.models import AgentState

    hub = Hub(settings, [])

    async def go():
        queue = await hub.subscribe()
        await hub.put_agent(AgentState(id="ghost", name="Ghost", source="config"))
        approval = await hub.create_approval("ghost", "deploy", "", "generic")
        await hub.remove_agent("ghost")
        return approval, drain(queue)

    approval, events = asyncio.run(go())
    assert "ghost" not in hub.agents
    assert approval.status == "expired"
    assert events[-1] == {"type": "agent_removed", "data": {"id": "ghost"}}


def test_put_agent_refreshes_descriptive_fields_but_keeps_live_status(settings):
    from agent_manager.models import AgentState

    hub = Hub(settings, [])

    async def go():
        await hub.put_agent(AgentState(id="bot", name="Bot", model="a/b", source="config"))
        await hub.set_status("bot", Status.working, task="build")
        await hub.put_agent(AgentState(id="bot", name="Bot 2", model="c/d", source="config"))

    asyncio.run(go())
    bot = hub.agents["bot"]
    assert (bot.name, bot.model, bot.status, bot.task) == ("Bot 2", "c/d", Status.working, "build")
