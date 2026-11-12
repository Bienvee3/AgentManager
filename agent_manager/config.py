"""Settings loader for agents.yaml."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
EXAMPLE_NAME = "agents.example.yaml"
FALLBACK_LOG = "Using agents.example.yaml (agents.yaml not found)"


@dataclass
class ServerSettings:
    host: str = "127.0.0.1"
    port: int = 8765


@dataclass
class HitlSettings:
    approval_timeout_s: float = 840
    tools_pattern: re.Pattern = field(default_factory=lambda: re.compile(r"(?!)"))
    command_patterns: list[re.Pattern] = field(default_factory=list)


@dataclass
class MonitorSettings:
    stale_check_interval_s: float = 5
    log_buffer: int = 500


@dataclass
class Settings:
    server: ServerSettings
    hitl: HitlSettings
    monitor: MonitorSettings
    agents_raw: list[dict[str, Any]]
    config_path: Path
    startup_logs: list[str] = field(default_factory=list)


def _resolve_path(path: str | None) -> tuple[Path, list[str]]:
    explicit = path or os.environ.get("AGENT_MANAGER_CONFIG")
    if explicit:
        return Path(explicit), []
    local = Path("agents.yaml")
    if local.exists():
        return local, []
    # Fall back to the example shipped next to the package, then to cwd.
    example = REPO_ROOT / EXAMPLE_NAME
    if not example.exists():
        example = Path(EXAMPLE_NAME)
    return example, [FALLBACK_LOG]


def _compile(pattern: str, where: str) -> re.Pattern:
    try:
        return re.compile(pattern, re.IGNORECASE)
    except re.error as exc:
        raise SystemExit(f"Invalid regex in {where}: {pattern!r} ({exc})") from None


def load_settings(path: str | None = None) -> Settings:
    cfg_path, startup_logs = _resolve_path(path)
    try:
        raw = yaml.safe_load(cfg_path.read_text(encoding="utf-8")) or {}
    except FileNotFoundError:
        raise SystemExit(f"Config file not found: {cfg_path}") from None
    except yaml.YAMLError as exc:
        raise SystemExit(f"Invalid YAML in {cfg_path}: {exc}") from None
    if not isinstance(raw, dict):
        raise SystemExit(f"Invalid config {cfg_path}: top level must be a mapping")

    srv = raw.get("server") or {}
    hitl = raw.get("hitl") or {}
    mon = raw.get("monitor") or {}
    try:
        settings = Settings(
            server=ServerSettings(host=str(srv.get("host", "127.0.0.1")), port=int(srv.get("port", 8765))),
            hitl=HitlSettings(
                approval_timeout_s=float(hitl.get("approval_timeout_s", 840)),
                tools_pattern=_compile(str(hitl.get("critical_tools") or r"(?!)"), "hitl.critical_tools"),
                command_patterns=[
                    _compile(str(p), "hitl.critical_command_patterns")
                    for p in hitl.get("critical_command_patterns") or []
                ],
            ),
            monitor=MonitorSettings(
                stale_check_interval_s=float(mon.get("stale_check_interval_s", 5)),
                log_buffer=int(mon.get("log_buffer", 500)),
            ),
            agents_raw=list(raw.get("agents") or []),
            config_path=cfg_path,
            startup_logs=startup_logs,
        )
    except (TypeError, ValueError) as exc:
        raise SystemExit(f"Invalid config {cfg_path}: {exc}") from None
    return settings
