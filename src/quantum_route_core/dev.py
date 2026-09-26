"""Start the local API and worker with `uv run dev` from the repository root."""

import argparse
import os
import signal
import socket
import subprocess
import sys
import time
from pathlib import Path


def stop_processes(processes: list[subprocess.Popen]) -> None:
    import psutil

    descendants = []
    for process in processes:
        if process.poll() is not None:
            continue
        try:
            descendants.extend(psutil.Process(process.pid).children(recursive=True))
            stop_signal = (
                signal.CTRL_BREAK_EVENT  # type: ignore[attr-defined]
                if os.name == "nt"
                else signal.SIGINT
            )
            process.send_signal(stop_signal)
        except (OSError, psutil.Error):
            pass
    deadline = time.monotonic() + 5
    for process in processes:
        try:
            process.wait(timeout=max(0.01, deadline - time.monotonic()))
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()
    # A solver subprocess must not survive its worker after a forced stop.
    for descendant in descendants:
        try:
            if descendant.is_running():
                descendant.kill()
        except psutil.Error:
            pass
    psutil.wait_procs(descendants, timeout=2)


def monitor(processes: list[subprocess.Popen]) -> None:
    while True:
        for name, process in zip(("Worker", "API"), processes, strict=True):
            if process.poll() is not None:
                print(f"{name} exited ({process.returncode}); stopping services.", file=sys.stderr)
                raise SystemExit(process.returncode or 1)
        time.sleep(0.2)


def main() -> None:
    parser = argparse.ArgumentParser(description="Start the local API and worker together.")
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()
    if not 1 <= args.port <= 65535:
        parser.error("port must be between 1 and 65535")
    if not Path("alembic.ini").is_file() or not Path("migrations").is_dir():
        parser.error("run this command from the repository root")
    try:
        from alembic import command
        from alembic.config import Config

        from quantum_route_core.api.settings import Settings
    except ImportError:
        parser.error("install service dependencies: uv sync --extra service --extra classical")
    Settings()  # Validate configuration before starting either service.
    try:
        with socket.socket() as probe:
            probe.bind(("127.0.0.1", args.port))
    except OSError:
        parser.error(f"port {args.port} is unavailable; choose another with --port")

    processes: list[subprocess.Popen] = []
    options = (
        {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP}  # type: ignore[attr-defined]
        if os.name == "nt"
        else {"start_new_session": True}
    )
    try:
        print("Preparing database...", flush=True)
        command.upgrade(Config("alembic.ini"), "head")
        processes.append(
            subprocess.Popen([sys.executable, "-m", "quantum_route_core.jobs.worker"], **options)
        )
        processes.append(
            subprocess.Popen(
                [
                    sys.executable,
                    "-m",
                    "uvicorn",
                    "quantum_route_core.api.app:create_app",
                    "--factory",
                    "--host",
                    "127.0.0.1",
                    "--port",
                    str(args.port),
                ],
                **options,
            )
        )
        print(
            f"Starting API at http://127.0.0.1:{args.port}\n"
            f"Open http://127.0.0.1:{args.port}/docs to use the endpoints.\n"
            "Press Ctrl+C to stop the API and worker.",
            flush=True,
        )
        monitor(processes)
    except KeyboardInterrupt:
        print("\nStopping API and worker...", flush=True)
    finally:
        stop_processes(processes)


if __name__ == "__main__":
    main()
