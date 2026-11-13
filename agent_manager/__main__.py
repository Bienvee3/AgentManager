"""Command line entry point: serve | watch | simulate."""

from __future__ import annotations

import argparse
import os
import sys

DEFAULT_URL = "http://127.0.0.1:8765"


def _default_url() -> str:
    return os.environ.get("AGENT_MANAGER_URL", DEFAULT_URL)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="agent_manager", description="Agent Manager")
    sub = parser.add_subparsers(dest="command", required=True)

    p_serve = sub.add_parser("serve", help="run the hub + web UI")
    p_serve.add_argument("--config", help="path to agents.yaml (omit to use the project's omp agents)")
    p_serve.add_argument("--project", help="project directory whose omp agents/sessions are shown (default: current directory)")
    p_serve.add_argument("--all", action="store_true", help="watch every omp project with an active session (one room each)")
    p_serve.add_argument("--host")
    p_serve.add_argument("--port", type=int)

    p_watch = sub.add_parser("watch", help="terminal UI with HITL approvals")
    p_watch.add_argument("--url", default=_default_url())

    p_sim = sub.add_parser("simulate", help="run simulated agents against a running manager")
    p_sim.add_argument("--url", default=_default_url())
    p_sim.add_argument("--seed", type=int, default=None)

    p_auto = sub.add_parser("install-autostart", help="start the manager (serve --all) when you log in to Windows")
    p_auto.add_argument("--port", type=int, default=8765)
    sub.add_parser("uninstall-autostart", help="remove the Windows login launcher")

    args = parser.parse_args(argv)

    if args.command == "serve":
        import uvicorn

        from .config import load_settings
        from .server import create_app

        settings = load_settings(args.config, args.project, args.all)
        if args.host:
            settings.server.host = args.host
        if args.port:
            settings.server.port = args.port
        uvicorn.run(
            create_app(settings),
            host=settings.server.host,
            port=settings.server.port,
            log_level="info",
        )
    elif args.command == "watch":
        from .tui import run_tui

        run_tui(args.url)
    elif args.command == "simulate":
        from .simulator import run_simulator

        run_simulator(args.url, args.seed)
    elif args.command == "install-autostart":
        from . import autostart

        print(f"Autostart installed: {autostart.install(args.port)}")
    elif args.command == "uninstall-autostart":
        from . import autostart

        print("Autostart removed" if autostart.uninstall() else "Autostart was not installed")


if __name__ == "__main__":
    sys.exit(main())
