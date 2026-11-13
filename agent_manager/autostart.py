"""Start the manager with Windows: a launcher in the user's Startup folder."""

from __future__ import annotations

import os
import sys
from pathlib import Path

LAUNCHER_NAME = "AgentManager.cmd"


def _require_windows() -> None:
    if os.name != "nt":
        raise SystemExit("Autostart is only supported on Windows")


def startup_dir() -> Path:
    return Path(os.environ["APPDATA"]) / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "Startup"


def install(port: int = 8765) -> Path:
    """Write the launcher; at login it starts `serve --all` minimized. Returns its path."""
    _require_windows()
    target = startup_dir() / LAUNCHER_NAME
    target.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "@echo off",
        'cd /d "%USERPROFILE%"',
        f'start "Agent Manager" /min "{sys.executable}" -m agent_manager serve --all --port {port}',
    ]
    target.write_bytes(("\r\n".join(lines) + "\r\n").encode("utf-8"))
    return target


def uninstall() -> bool:
    """Remove the launcher. True if one was removed."""
    _require_windows()
    target = startup_dir() / LAUNCHER_NAME
    if not target.exists():
        return False
    target.unlink()
    return True
