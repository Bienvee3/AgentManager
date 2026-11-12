def _create(client, agent_id="alpha", **body):
    body = {"action": "git push origin main", "details": "git push", "kind": "deploy", **body}
    res = client.post(f"/api/agents/{agent_id}/approvals", json=body)
    assert res.status_code == 201, res.text
    return res.json()


def _agent(client, agent_id="alpha"):
    return next(a for a in client.get("/api/agents").json() if a["id"] == agent_id)


def test_create_sets_waiting_approval(client):
    approval = _create(client)
    assert approval["status"] == "pending"
    agent = _agent(client)
    assert agent["status"] == "waiting_approval"
    assert agent["pending_approvals"] == 1


def test_approve_resumes_agent(client):
    approval = _create(client)
    res = client.post(f"/api/approvals/{approval['id']}/approve", json={"via": "web"})
    assert res.status_code == 200
    assert res.json()["status"] == "approved"
    assert res.json()["decided_via"] == "web"
    agent = _agent(client)
    assert agent["status"] == "working"
    assert agent["detail"].startswith("Aprobado: ")
    assert agent["pending_approvals"] == 0


def test_double_decision_conflicts(client):
    approval = _create(client)
    assert client.post(f"/api/approvals/{approval['id']}/approve", json={}).status_code == 200
    res = client.post(f"/api/approvals/{approval['id']}/approve", json={})
    assert res.status_code == 409
    assert res.json()["detail"] == "Approval already approved"
    assert client.post(f"/api/approvals/{approval['id']}/reject", json={}).status_code == 409


def test_reject_pauses_agent(client):
    approval = _create(client)
    res = client.post(f"/api/approvals/{approval['id']}/reject", json={"reason": "no", "via": "tui"})
    assert res.json()["status"] == "rejected"
    agent = _agent(client)
    assert agent["status"] == "paused"
    assert agent["detail"].startswith("Rechazado: ")


def test_agent_stays_waiting_while_other_approvals_pending(client):
    first = _create(client, action="one")
    _create(client, action="two")
    client.post(f"/api/approvals/{first['id']}/approve", json={})
    agent = _agent(client)
    assert agent["status"] == "waiting_approval"
    assert agent["pending_approvals"] == 1


def test_expiry_is_a_rejection(client):
    approval = _create(client, timeout_s=0.2)
    res = client.get(f"/api/approvals/{approval['id']}?wait=2")
    assert res.json()["status"] == "expired"
    assert res.json()["reason"] == "Timeout"
    assert _agent(client)["status"] == "paused"


def test_long_poll_returns_on_decision(client):
    approval = _create(client)
    client.post(f"/api/approvals/{approval['id']}/approve", json={})
    res = client.get(f"/api/approvals/{approval['id']}?wait=5")
    assert res.json()["status"] == "approved"


def test_unknown_ids_are_404(client):
    assert client.post("/api/agents/nope/approvals", json={"action": "x"}).status_code == 404
    assert client.get("/api/approvals/nope").status_code == 404
    assert client.post("/api/approvals/nope/approve", json={}).json()["detail"] == "Unknown approval 'nope'"


def test_callback_failure_is_logged(client, monkeypatch):
    from agent_manager import hitl_callbacks

    async def boom(approval, agent):
        raise RuntimeError("kaput")

    monkeypatch.setattr(hitl_callbacks, "on_approved", boom)
    approval = _create(client)
    client.post(f"/api/approvals/{approval['id']}/approve", json={})
    logs = client.get("/api/state").json()["logs"]
    assert any(e["level"] == "error" and e["message"] == "HITL callback failed: kaput" for e in logs)
