# Failure recovery

| Failure point | Durable state | Recovery |
|---|---|---|
| API fails before commit | No accepted job | Retry with same idempotency key |
| API response lost after commit | Pending or later state | Same key returns same job |
| Redis publish fails | Pending row committed | Scheduler republishes when Redis returns |
| Redis ready set disappears | Jobs remain in PostgreSQL | Scheduler rebuilds due pending set |
| Worker dies after pop, before claim | Pending | Next scheduler scan republishes |
| Worker dies after claim | Running lease | Expiry + retry policy + due-time publication |
| Handler effects succeed, outcome missing | Running/expired | Retry; handler must deduplicate effects |
| Old worker returns after recovery | Different/expired lease token | Completion rejected |
| DB connection drops during execution | Commit may be unknown | Supervisor stops child, lease recovery; inspect durable state |
| Scheduler is stopped | Durable rows remain | Resume scheduler; recovery is delayed while absent |

Database connections use pool_pre_ping. Supervisors and scheduler catch infrastructure
exceptions, log only exception type and retry polling. The API maps database errors to
503, advising reuse of an idempotency key. A Redis publication failure does not undo
an already committed job. Readiness returns 503 if either dependency is unavailable;
liveness indicates only that the API process is responsive.

SIGTERM asks a worker to stop. If a task is active, its child is terminated and its
lease is left for recovery; shutdown does not falsely report success. SIGKILL cannot
run cleanup. An orphan child can continue until its bounded task ends, so even after
recovery there can be overlapping physical work. Durable ownership remains fenced.

## Automated demonstration

With Docker services running, stop the Compose workers while leaving API and scheduler
up. Run the demo from your host virtual environment using the generated .env:

```bash
docker compose stop worker
python scripts/crash_demo.py
docker compose up -d --scale worker=3 worker
```

The script submits a three-second task, starts its own worker, waits for RUNNING,
kills that process, starts a replacement, and prints attempt history plus measured
kill-to-completion latency. It kills only processes it started. Do not run unrelated
workers against this queue during the demonstration. First let any pending queue
backlog drain: a worker processes earlier claimed jobs before it can claim the demo
job. The script reports its job ID and status while waiting up to four minutes;
this wait is for a claim, not part of the measured recovery time. The Windows native
test suite already contains an isolated worker-kill recovery check.

The test suite has a real process-kill test, expired-token rejection, exhausted crash
budget, duplicate delivery, ready-index loss and a simulated Redis publish outage.
Native PostgreSQL backend termination and simultaneous claim tests are separate from
PGlite compatibility checks. See verification.md for exactly which checks ran.

Default recovery latency is approximately remaining lease time (up to 15s), scheduler
polling, retry backoff (2s for first retry), queue waiting, child startup and execution.
This is not a fixed SLA. Recovery can be longer during infrastructure failure or load.

## Redis outage experiment on your local stack

Stop Redis with `docker compose stop redis`, submit a job (the durable API accepts it),
then `docker compose start redis`. Observe it complete after scheduler publication.
`/ready` should show 503 during the outage. Do not claim this full service-stop
experiment was executed unless you actually run it; the included tests currently
cover injected publication failure and actual Redis key loss instead.
