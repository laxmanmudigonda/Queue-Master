"""Run against ONLY the dedicated compose.test.yml services. Requires pip install -e '.[dev]'."""

import os
import subprocess
import sys

from dotenv import dotenv_values

config = dotenv_values(".env")
password = config["POSTGRES_PASSWORD"]
url = f"postgresql+psycopg://queuemaster:{password}@127.0.0.1:15433/queuemaster_test"
env = {
    **os.environ,
    "DATABASE_URL": url,
    "TEST_DATABASE_URL": url,
    "REDIS_URL": "redis://127.0.0.1:16380/0",
    "API_KEY": config["API_KEY"],
    "QUEUE_KEY": "queuemaster:test:ready",
}
env.pop("PGLITE_VALIDATION", None)
subprocess.run([sys.executable, "-m", "alembic", "upgrade", "head"], env=env, check=True)
subprocess.run(
    [sys.executable, "-m", "pytest", "-q", "-s", "--junitxml=docs/native-test-results.xml"],
    env=env,
    check=True,
)
