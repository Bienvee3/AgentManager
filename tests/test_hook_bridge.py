def _hook(client, payload, agent_id="oi-demo"):
    res = client.post("/api/hooks/openinterpreter", json={"agent_id": agent_id, "payload": payload})
    assert res.status_code == 200, res.text
    return res.json()


def _agent(client, agent_id):
    return next(a for a in client.get("/api/agents").json() if a["id"] == agent_id)


def test_critical_command_creates_approval(client):
    res = _hook(
        client,
        {"hook_event_name": "PreToolUse", "tool_name": "Bash", "tool_input": {"command": "git push origin main"}},
    )
    assert res["action"] == "pending"
    assert res["approval"]["kind"] == "tool_call"
    assert res["approval"]["details"] == "git push origin main"
    assert _agent(client, "oi-demo")["status"] == "waiting_approval"
    assert len(client.get("/api/state").json()["approvals"]) == 1


def test_harmless_command_is_allowed_and_logged(client):
    res = _hook(
        client,
        {"hook_event_name": "PreToolUse", "tool_name": "Bash", "tool_input": {"command": "dir"}},
    )
    assert res == {"action": "allow"}
    logs = client.get("/api/state").json()["logs"]
    assert any(e["agent_id"] == "oi-demo" and e["message"] == "Bash: dir" for e in logs)


def test_critical_tool_name(client):
    res = _hook(client, {"hook_event_name": "PreToolUse", "tool_name": "apply_patch", "tool_input": {"x": 1}})
    assert res["action"] == "pending"


def test_stop_waits_for_input(client):
    _hook(client, {"hook_event_name": "Stop"})
    assert _agent(client, "oi-demo")["status"] == "waiting_input"


def test_unknown_agent_is_registered_as_runtime(client):
    _hook(client, {"hook_event_name": "SessionStart"}, agent_id="oi-new")
    agent = _agent(client, "oi-new")
    assert agent["source"] == "runtime"
    assert agent["name"] == "oi-new"
    assert agent["status"] == "working"


def test_prompt_becomes_task_truncated(client):
    _hook(client, {"hook_event_name": "UserPromptSubmit", "prompt": "x" * 100})
    assert _agent(client, "oi-demo")["task"] == "x" * 48


def test_missing_fields_degrade_gracefully(client):
    assert _hook(client, {"hook_event_name": "PreToolUse"}) == {"action": "allow"}
    assert _hook(client, {}) == {"action": "allow"}
