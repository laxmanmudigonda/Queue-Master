"""Optional restricted-host compatibility harness, not production PostgreSQL.
Install Node dependencies in this directory first. Supply an actual redis-server binary.
All services/tests share this subprocess tree and use disposable local data.
"""

import argparse
import os
import secrets
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path


def wait_port(port):
    for _ in range(150):
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.2):
                return
        except OSError:
            time.sleep(0.2)
    raise RuntimeError(f"Service port {port} unavailable")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--redis-server", required=True)
    parser.add_argument("--benchmark", action="store_true")
    args = parser.parse_args()
    here = Path(__file__).resolve().parent
    root = here.parent.parent
    url = "postgresql+psycopg://postgres@127.0.0.1:15432/postgres"
    env = {
        **os.environ,
        "DATABASE_URL": url,
        "TEST_DATABASE_URL": url,
        "REDIS_URL": "redis://127.0.0.1:16379/0",
        "API_KEY": secrets.token_hex(32),
        "PGLITE_VALIDATION": "1",
        "PYTHONPATH": os.pathsep.join([str(here), str(root)]),
    }
    processes = []
    with tempfile.TemporaryDirectory(prefix="qm-compat-") as tmp:
        try:
            cli = (
                here
                / "node_modules"
                / "@electric-sql"
                / "pglite-socket"
                / "dist"
                / "scripts"
                / "server.js"
            )
            # Resolve the package's installed CLI from its declared bin entry.
            import json

            package = here / "node_modules" / "@electric-sql" / "pglite-socket" / "package.json"
            entry = json.loads(package.read_text())["bin"]["pglite-server"]
            cli = package.parent / entry
            processes.append(
                subprocess.Popen(
                    ["node", str(cli), "--port=15432", "--max-connections=30", f"--db={tmp}/pg"],
                    env=env,
                    cwd=root,
                )
            )
            processes.append(
                subprocess.Popen(
                    [
                        args.redis_server,
                        "--port",
                        "16379",
                        "--bind",
                        "127.0.0.1",
                        "--save",
                        "",
                        "--appendonly",
                        "no",
                    ],
                    env=env,
                    cwd=root,
                )
            )
            wait_port(15432)
            wait_port(16379)
            subprocess.run(
                [sys.executable, "-m", "alembic", "upgrade", "head"], env=env, cwd=root, check=True
            )
            subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "pytest",
                    "-q",
                    "-s",
                    "--junitxml=docs/compatibility-test-results.xml",
                ],
                env=env,
                cwd=root,
                check=True,
            )
            if args.benchmark:
                processes.append(
                    subprocess.Popen(
                        [
                            sys.executable,
                            "-m",
                            "uvicorn",
                            "app.main:app",
                            "--host",
                            "127.0.0.1",
                            "--port",
                            "8000",
                        ],
                        env=env,
                        cwd=root,
                    )
                )
                wait_port(8000)
                subprocess.run(
                    [
                        sys.executable,
                        "scripts/benchmark.py",
                        "--environment",
                        "PGlite WASM compatibility harness; Redis local; host hardware unspecified; NOT native PostgreSQL performance",
                    ],
                    env=env,
                    cwd=root,
                    check=True,
                )
        finally:
            for p in reversed(processes):
                p.terminate()
            for p in processes:
                try:
                    p.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    p.kill()
                    p.wait()


if __name__ == "__main__":
    main()
