import threading
import time

import httpx
import pytest

from agent_manager.client import AgentManagerClient, AgentManagerUnavailable


def _run_request(client: AgentManagerClient) -> dict:
    out: dict = {}

    def target():
        out["decision"] = client.request_approval("Deploy", details="deploy now", kind="deploy")

    thread = threading.Thread(target=target)
    thread.start()
    out["thread"] = thread
    return out


def _wait_pending(base_url: str) -> str:
    deadline = time.time() + 5
    while time.time() < deadline:
        approvals = httpx.get(f"{base_url}/api/state").json()["approvals"]
        if approvals:
            return approvals[0]["id"]
        time.sleep(0.05)
    raise AssertionError("approval never became pending")


@pytest.mark.parametrize("verdict,expected", [("approve", True), ("reject", False)])
def test_request_approval_follows_decision(live_server, verdict, expected):
    client = AgentManagerClient("e2e-agent", base_url=live_server)
    client.register(heartbeat_interval_s=None)
    out = _run_request(client)
    approval_id = _wait_pending(live_server)
    res = httpx.post(f"{live_server}/api/approvals/{approval_id}/{verdict}", json={"via": "api", "reason": "ok"})
    assert res.status_code == 200
    out["thread"].join(timeout=10)
    assert not out["thread"].is_alive()
    assert out["decision"].approved is expected
    assert out["decision"].reason == "ok"


def test_unreachable_manager_raises():
    client = AgentManagerClient("nobody", base_url="http://127.0.0.1:1", timeout=2)
    with pytest.raises(AgentManagerUnavailable):
        client.register()


def test_http_error_becomes_runtime_error(live_server):
    client = AgentManagerClient("ghost", base_url=live_server)
    with pytest.raises(RuntimeError, match="404"):
        client.status("working")
