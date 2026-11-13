import os
import sys

import pytest

from agent_manager import autostart

pytestmark = pytest.mark.skipif(os.name != "nt", reason="autostart is Windows-only")


def test_install_writes_launcher_that_serves_all_projects_and_uninstall_removes_it(tmp_path, monkeypatch):
    monkeypatch.setenv("APPDATA", str(tmp_path))
    path = autostart.install(8799)
    assert path == autostart.startup_dir() / "AgentManager.cmd"
    text = path.read_text(encoding="utf-8")
    assert f'"{sys.executable}" -m agent_manager serve --all --port 8799' in text
    assert b"\r\n" in path.read_bytes()  # cmd.exe needs CRLF line endings
    assert autostart.uninstall() is True
    assert not path.exists()
    assert autostart.uninstall() is False
