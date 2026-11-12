"""Simulator: demo and exercise the UI without real agents.

Spawns one thread per example agent, each looping over a scripted behaviour
through the stdlib client (the same path real agents use).
"""

from __future__ import annotations

import random
import sys
import threading
import time
from collections.abc import Callable

from agent_manager.client import AgentManagerClient, AgentManagerUnavailable

HEARTBEAT_S = 5

# Same agents as agents.example.yaml; registering them upserts, so entries
# that already exist as config agents keep their source.
SIM_AGENTS: list[dict] = [
    {"id": "refactor-bot", "name": "Refactor-Bot", "role": "Code refactor", "avatar": 0},
    {"id": "data-cruncher", "name": "Data-Cruncher", "role": "Data pipeline", "avatar": 1},
    {"id": "deploy-agent", "name": "Deploy-Agent", "role": "Releases", "avatar": 2},
    {"id": "qa-tester", "name": "QA-Tester", "role": "Testing", "avatar": 3},
]


class _Stopped(Exception):
    """Raised inside a script when the simulator is shutting down."""


class _Script:
    def __init__(self, client: AgentManagerClient, rng: random.Random, stop: threading.Event) -> None:
        self.client = client
        self.rng = rng
        self.stop = stop

    def sleep(self, seconds: float) -> None:
        if self.stop.wait(seconds):
            raise _Stopped

    def pause(self, low: float = 2.0, high: float = 4.0) -> None:
        self.sleep(self.rng.uniform(low, high))

    # -- scripts (one iteration of each loop per call) -----------------------

    def refactor_bot(self, state: dict) -> None:
        c = self.client
        if "next_approval" not in state:
            state["next_approval"] = time.monotonic() + 40
            state["tasks"] = ["Code refactor", "Renombrando módulos", "Extrayendo servicios"]
            state["i"] = 0
        task = state["tasks"][state["i"] % len(state["tasks"])]
        state["i"] += 1
        c.status("working", task=task, detail="")
        for step in range(self.rng.randint(2, 4)):
            c.log(f"{task}: paso {step + 1}")
            self.pause()
            if time.monotonic() >= state["next_approval"]:
                decision = c.request_approval("Modificar 12 archivos en src/", kind="file_change")
                c.log("Cambios aplicados" if decision.approved else "Cambios descartados")
                c.status("working", task=task, detail="")
                state["next_approval"] = time.monotonic() + 40
                break

    def data_cruncher(self, state: dict) -> None:
        c = self.client
        n = state.get("batch", 0) % 50 + 1
        state["batch"] = n
        c.status("working", task="[Procesando Data]", detail="")
        c.log(f"Batch {n}/50")
        self.pause()
        if self.rng.random() < 0.15:
            c.status("error", error_kind="rate_limit", detail="Límite de API alcanzado")
            c.log("Rate limit alcanzado, reintentando en 10 s", "error")
            self.sleep(10)
            c.status("working", task="[Procesando Data]", detail="")

    def deploy_agent(self, state: dict) -> None:
        c = self.client
        c.status("working", task="Build", detail="")
        for step in ("Compilando", "Ejecutando linters", "Empaquetando artefactos"):
            c.log(f"Build: {step}")
            self.pause()
        decision = c.request_approval(
            "git push origin main → producción",
            details="git push origin main\n# despliegue a prod",
            kind="deploy",
        )
        if decision.approved:
            c.status("working", task="Desplegando", detail="")
            c.log("Desplegando a producción")
            self.sleep(6)
            c.status("idle", task="", detail="Despliegue completado")
            c.log("Despliegue completado")
            self.pause(8, 12)
        else:
            c.status("paused", detail="Despliegue cancelado")
            c.log("Despliegue cancelado", "warn")
            self.sleep(10)

    def qa_tester(self, state: dict) -> None:
        c = self.client
        n = state.get("suite", 0) + 1
        state["suite"] = n
        c.status("working", task="Ejecutando tests", detail="")
        c.log(f"Suite unitaria #{n}: {self.rng.randint(180, 240)} tests OK")
        self.pause()
        if self.rng.random() < 0.3:
            c.status("waiting_input", detail="¿Ejecutar suite e2e?")
            c.log("Esperando confirmación para la suite e2e", "warn")
            self.sleep(15)
            c.status("working", task="Ejecutando tests", detail="")


_SCRIPTS: dict[str, Callable[[_Script, dict], None]] = {
    "refactor-bot": _Script.refactor_bot,
    "data-cruncher": _Script.data_cruncher,
    "deploy-agent": _Script.deploy_agent,
    "qa-tester": _Script.qa_tester,
}


def _worker(script: _Script, step: Callable[[_Script, dict], None]) -> None:
    state: dict = {}
    while not script.stop.is_set():
        try:
            step(script, state)
        except _Stopped:
            return
        except (AgentManagerUnavailable, RuntimeError) as exc:
            # Manager restarted or went away: report and re-register once it is back.
            sys.stderr.write(f"[simulator:{script.client.agent_id}] {exc}\n")
            try:
                script.sleep(2)
                script.client.register(heartbeat_interval_s=HEARTBEAT_S)
            except (_Stopped, AgentManagerUnavailable, RuntimeError):
                pass


def run_simulator(url: str, seed: int | None) -> None:
    master = random.Random(seed)
    stop = threading.Event()
    clients: list[AgentManagerClient] = []
    threads: list[threading.Thread] = []

    for spec in SIM_AGENTS:
        client = AgentManagerClient(spec["id"], name=spec["name"], role=spec["role"], avatar=spec["avatar"], base_url=url)
        try:
            client.register(heartbeat_interval_s=HEARTBEAT_S)
        except AgentManagerUnavailable:
            for started in clients:
                started.close()
            print(f"Agent Manager not reachable at {url}", file=sys.stderr)
            raise SystemExit(1) from None
        client.start_heartbeat(HEARTBEAT_S)
        clients.append(client)
        script = _Script(client, random.Random(master.random()), stop)
        threads.append(
            threading.Thread(
                target=_worker, args=(script, _SCRIPTS[spec["id"]]), name=f"sim-{spec['id']}", daemon=True
            )
        )

    for thread in threads:
        thread.start()
    print(f"Simulating {len(clients)} agents against {url} (Ctrl+C to stop)")
    try:
        while any(t.is_alive() for t in threads):
            stop.wait(0.5)
    except KeyboardInterrupt:
        print("Stopping simulator...")
    finally:
        stop.set()
        for thread in threads:
            thread.join(timeout=1.5)
        for client in clients:
            client.close()
