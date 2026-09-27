import os

# Unit tests need no services. Integration tests require an explicitly isolated URL.
os.environ.setdefault("DATABASE_URL", os.getenv("TEST_DATABASE_URL", "sqlite://"))
os.environ.setdefault("API_KEY", "unit-tests-only-not-a-deployment-key")

import pytest
from sqlalchemy import text

from app.db import Session
from app.queue import redis


@pytest.fixture
def infrastructure():
    if not os.getenv("TEST_DATABASE_URL"):
        pytest.skip("Set TEST_DATABASE_URL to an isolated migrated PostgreSQL database")
    if os.environ["DATABASE_URL"] != os.environ["TEST_DATABASE_URL"]:
        pytest.fail("DATABASE_URL must equal TEST_DATABASE_URL; never reset a production database")
    with Session.begin() as s:
        s.execute(text("TRUNCATE effects, counters, events, attempts, jobs, workers CASCADE"))
    redis.delete(os.getenv("QUEUE_KEY", "queuemaster:ready"))
    yield
