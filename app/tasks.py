import csv
import io
import time
from typing import Annotated, Any

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert

from app.db import Counter, Effect, Job, Session


class Payload(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Fibonacci(Payload):
    n: int = Field(ge=0, le=10000)


class Report(Payload):
    rows: list[dict[str, str | int | float]] = Field(max_length=1000)


class Document(Payload):
    text: str = Field(max_length=100000)
    filename: str = Field(default="document.txt", max_length=255)


class Failure(Payload):
    failures: int = Field(ge=0, le=100)


class LongRunning(Payload):
    seconds: float = Field(ge=0, le=300)


class CounterPayload(Payload):
    name: Annotated[str, Field(pattern=r"^[a-zA-Z0-9_-]{1,64}$")]


REGISTRY = {
    "fibonacci": Fibonacci,
    "generate_report": Report,
    "document_processing": Document,
    "simulated_failure": Failure,
    "long_running": LongRunning,
    "idempotent_counter": CounterPayload,
}


def validate(task_type: str, payload: dict[str, Any]) -> dict[str, Any]:
    if task_type not in REGISTRY:
        raise ValueError("Unknown task type")
    return REGISTRY[task_type].model_validate(payload).model_dump()


def csv_cell(value: str | int | float) -> str | int | float:
    if isinstance(value, str) and (
        value.lstrip().startswith(("=", "+", "-", "@")) or value.startswith(("\t", "\r", "\n"))
    ):
        return "'" + value
    return value


def execute(task_type: str, payload: dict[str, Any], job_id: str, attempt: int) -> dict[str, Any]:
    p = validate(task_type, payload)
    if task_type == "fibonacci":
        a, b = 0, 1
        for _ in range(p["n"]):
            a, b = b, a + b
        return {"value": str(a), "n": p["n"]}
    if task_type == "generate_report":
        output = io.StringIO()
        fields = sorted({k for row in p["rows"] for k in row})
        writer = csv.DictWriter(output, fieldnames=fields)
        writer.writerow({key: csv_cell(key) for key in fields})
        # Neutralize spreadsheet formula injection in user-supplied cells.
        for row in p["rows"]:
            writer.writerow({k: csv_cell(v) for k, v in row.items()})
        return {"csv": output.getvalue(), "rows": len(p["rows"])}
    if task_type == "document_processing":
        return {
            "word_count": len(p["text"].split()),
            "character_count": len(p["text"]),
            "line_count": len(p["text"].splitlines()),
            "filename": p["filename"],
        }
    if task_type == "simulated_failure":
        if attempt <= p["failures"]:
            raise RuntimeError("Configured demonstration failure")
        return {"attempt": attempt}
    if task_type == "long_running":
        time.sleep(p["seconds"])
        return {"slept_seconds": p["seconds"]}
    # Serialize repeated effects for this job; increment and receipt commit together.
    with Session.begin() as s:
        s.execute(select(Job).where(Job.id == job_id).with_for_update()).scalar_one()
        receipt = s.get(Effect, job_id)
        if receipt:
            return receipt.result
        statement = insert(Counter).values(name=p["name"], value=1)
        value = s.execute(
            statement.on_conflict_do_update(
                index_elements=[Counter.name], set_={"value": Counter.value + 1}
            ).returning(Counter.value)
        ).scalar_one()
        result = {"name": p["name"], "value": value}
        s.add(Effect(job_id=job_id, result=result))
        return result
