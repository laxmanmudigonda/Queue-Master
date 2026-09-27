from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from app.main import Submission
from app.service import TRANSITIONS, Conflict, backoff, transition
from app.tasks import REGISTRY, execute, validate


@pytest.mark.parametrize(
    "task,payload",
    [
        ("fibonacci", {"n": -1}),
        ("fibonacci", {"n": 10001}),
        ("long_running", {"seconds": 301}),
        ("unknown", {}),
        ("document_processing", {"text": "a", "unexpected": True}),
    ],
)
def test_validation(task, payload):
    with pytest.raises((ValueError, ValidationError)):
        validate(task, payload)


def test_timezone_required():
    with pytest.raises(ValidationError):
        Submission(task_type="fibonacci", payload={"n": 1}, scheduled_at="2026-01-01T00:00:00")


def test_backoff_cap():
    assert backoff(1) == 2
    assert backoff(2) == 4
    assert backoff(1000) == 60


@pytest.mark.parametrize("old", TRANSITIONS)
@pytest.mark.parametrize("new", TRANSITIONS)
def test_state_machine(old, new):
    events = []
    session = SimpleNamespace(add=events.append)
    job = SimpleNamespace(id="test", status=old)
    if new in TRANSITIONS[old]:
        transition(session, job, new)
        assert job.status == new and len(events) == 1
    else:
        with pytest.raises(Conflict):
            transition(session, job, new)


def test_registered_tasks():
    assert len(REGISTRY) == 6
    assert execute("fibonacci", {"n": 25}, "x", 1)["value"] == "75025"
    assert execute("document_processing", {"text": "hello world\nnext"}, "x", 1)["word_count"] == 3
    assert "'=1" in execute("generate_report", {"rows": [{"x": "=1"}]}, "x", 1)["csv"]
    assert execute("long_running", {"seconds": 0}, "x", 1)["slept_seconds"] == 0
    with pytest.raises(RuntimeError):
        execute("simulated_failure", {"failures": 1}, "x", 1)
    assert execute("simulated_failure", {"failures": 1}, "x", 2)["attempt"] == 2


def test_csv_formula_headers_and_leading_whitespace():
    result = execute(
        "generate_report", {"rows": [{"=header": "  =formula", "plain": "ok"}]}, "x", 1
    )
    assert "'=header" in result["csv"]
    assert "'  =formula" in result["csv"]
