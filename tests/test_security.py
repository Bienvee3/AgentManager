import pytest
from starlette.websockets import WebSocketDisconnect


def test_post_without_json_content_type_is_415(client):
    res = client.post("/api/agents/alpha/heartbeat", content="{}", headers={"content-type": "text/plain"})
    assert res.status_code == 415
    assert res.json() == {"detail": "Content-Type must be application/json"}


def test_post_with_json_content_type_charset_ok(client):
    res = client.post("/api/agents/alpha/heartbeat", content="{}", headers={"content-type": "application/json; charset=utf-8"})
    assert res.status_code == 204


def test_ws_rejects_foreign_origin(client):
    with pytest.raises(WebSocketDisconnect) as exc:
        with client.websocket_connect("/ws", headers={"origin": "http://evil.example"}):
            pass
    assert exc.value.code == 1008


def test_ws_allows_local_origin_and_no_origin(client):
    with client.websocket_connect("/ws", headers={"origin": "http://localhost:8765"}) as ws:
        assert ws.receive_json()["type"] == "snapshot"
    with client.websocket_connect("/ws") as ws:
        assert ws.receive_json()["type"] == "snapshot"


def test_ws_streams_incremental_events(client):
    with client.websocket_connect("/ws") as ws:
        snap = ws.receive_json()
        assert [a["id"] for a in snap["data"]["agents"]] == ["alpha", "beta"]
        assert all(a["status"] == "offline" for a in snap["data"]["agents"])
        client.post("/api/agents/alpha/status", json={"status": "working", "task": "x"})
        events = [ws.receive_json(), ws.receive_json()]
        assert {e["type"] for e in events} == {"log", "agent"}
        agent_event = next(e for e in events if e["type"] == "agent")
        assert agent_event["data"]["status"] == "working"


def test_invalid_status_is_422(client):
    assert client.post("/api/agents/alpha/status", json={"status": "bogus"}).status_code == 422


def test_unknown_agent_status_is_404(client):
    res = client.post("/api/agents/nope/status", json={"status": "idle"})
    assert res.status_code == 404
    assert res.json()["detail"] == "Unknown agent 'nope'"
