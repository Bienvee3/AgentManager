import time


def test_silent_agent_is_marked_lost(client):
    client.post("/api/agents", json={"id": "ghost", "heartbeat_interval_s": 0.05})
    time.sleep(0.4)
    agent = next(a for a in client.get("/api/agents").json() if a["id"] == "ghost")
    assert agent["status"] == "error"
    assert agent["error_kind"] == "lost"


def test_heartbeating_agent_stays_alive(client):
    client.post("/api/agents", json={"id": "alive", "heartbeat_interval_s": 0.2})
    for _ in range(8):
        client.post("/api/agents/alive/heartbeat", json={})
        time.sleep(0.1)
    agent = next(a for a in client.get("/api/agents").json() if a["id"] == "alive")
    assert agent["status"] == "idle"
