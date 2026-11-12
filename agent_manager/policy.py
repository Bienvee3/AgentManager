"""Critical-action classification for HITL."""

from __future__ import annotations

import json
from typing import Any

from .config import HitlSettings


def classify(tool_name: str, command: str, hitl: HitlSettings) -> tuple[bool, str]:
    if tool_name and hitl.tools_pattern.search(tool_name):
        return True, f"critical tool {tool_name}"
    for pattern in hitl.command_patterns:
        if pattern.search(command or ""):
            return True, f"matches {pattern.pattern}"
    return False, ""


def command_text(tool_input: Any) -> str:
    if isinstance(tool_input, str):
        return tool_input
    if isinstance(tool_input, dict):
        cmd = tool_input.get("command")
        if isinstance(cmd, str):
            return cmd
        if isinstance(cmd, list):
            return " ".join(str(part) for part in cmd)
    return json.dumps(tool_input, default=str)[:4000]
