import socket
import sys
import threading
import time
from pathlib import Path

import pytest
import uvicorn
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from agent_manager.config import load_settings  # noqa: E402
from agent_manager.server import create_app  # noqa: E402

YAML = """
server: {host: 127.0.0.1, port: 8765}
hitl:
  approval_timeout_s: 30
  critical_tools: '^(apply_patch|Edit|Write|MultiEdit)$'
  critical_command_patterns:
    - '\\bgit\\s+push\\b'
monitor: {stale_check_interval_s: 0.05, log_buffer: 500}
agents:
  - {id: alpha, name: Alpha, role: Tester, avatar: 0}
  - {id: beta, name: Beta, role: Tester, avatar: 1}
"""


@pytest.fixture
def settings(tmp_path):
    path = tmp_path / "agents.yaml"
    path.write_text(YAML, encoding="utf-8")
    return load_settings(str(path))


@pytest.fixture
def client(settings):
    with TestClient(create_app(settings)) as c:
        yield c


@pytest.fixture
def live_server(settings):
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    settings.server.port = port
    server = uvicorn.Server(uvicorn.Config(create_app(settings), host="127.0.0.1", port=port, log_level="warning"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    deadline = time.time() + 10
    while not server.started:
        assert time.time() < deadline, "live server did not start"
        time.sleep(0.02)
    yield f"http://127.0.0.1:{port}"
    server.should_exit = True
    thread.join(timeout=10)
