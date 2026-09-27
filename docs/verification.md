# Delivery verification — 26 September 2026

## Subsequent Windows verification — 27 September 2026

The project owner ran `python scripts/test_native.py` against the isolated native
PostgreSQL and Redis test services: **63 tests passed in 45.56 seconds**. The
worker-kill recovery test reported approximately **20.57 seconds** to recover;
Windows printed `WinError 5` during forced termination, but the test passed.
Docker Compose also ran the API, scheduler and three workers, and live API requests
demonstrated job processing, retries, dead-letter jobs, idempotency and statistics.
The standalone `crash_demo.py` did not complete a separate live demonstration:
one submitted job waited around 137 seconds to be claimed and was then completed
on its first attempt, exceeding the script's former 30-second observation window.
The script has since been updated to report status and wait longer; that change has
not yet been verified on Windows. The dashboard added after these native tests has
been statically checked, not yet browser-tested on the owner's machine.

## What actually ran

- Python 3.12.14 on a restricted Linux runtime; exact library versions in
  python-versions.txt. Native Redis 7.0.15 on loopback.
- Alembic upgrade applied to PGlite's PostgreSQL engine through its socket proxy.
  Downgrade-to-base / re-upgrade succeeded; Alembic reported no schema drift before
  and after that round trip. This operated only on disposable verification data.
- Real FastAPI ASGI requests and a separately started Uvicorn HTTP server.
- Real independent worker processes, spawned task children and scheduler process.
- 61 tests passed; two skipped because they require native PostgreSQL backend/locking
  behavior. Raw report: test-results.xml. One dependency deprecation warning concerns
  Starlette's current HTTPX TestClient adapter, not a failed assertion.
- Tests exercised authentication/validation/body bounds, idempotency conflicts,
  persistent results, priorities, delay, cancellation, retry budgets, dead-letter,
  manual retry, expired leases, stale-result rejection, actual Redis ready-key loss,
  injected Redis publication failure, counter receipts and connection-pool recreation.
- Actual worker termination followed by lease recovery and successful replacement.
  The process-crash test prints measured kill-to-completion time in validation-run.log.
- Two independently registered workers processed overlapping two-second jobs.
- A two-second task completed with a one-second renewed lease and only one attempt.
- 100/1,000-job workloads with one/four worker processes: raw measurements in
  benchmark-results.json and table in benchmarks.md. These are compatibility-runtime
  results, not native PostgreSQL performance measurements.
- Ruff lint/format checks and Python byte-compilation. OpenAPI exported from the app.

An earlier PGlite run exposed a socket-protocol incompatibility around transaction
errors. The validation-only simple-query adapter is documented in
compatibility-runtime.md. Production code retains the ordinary Psycopg transport.
A broken-pipe traceback after killing a supervisor was also fixed so orphan children
exit quietly when they cannot report their bounded result.

## Explicitly outstanding

| Acceptance item | Status / next action |
|---|---|
| Native PostgreSQL simultaneous claim and concurrent idempotency races | Implemented test, skipped here; run scripts/test_native.py |
| Native PostgreSQL terminated-backend reconnection | Implemented test, skipped here; run scripts/test_native.py |
| Full PostgreSQL service outage/restart under load | Not run; pool recreation is weaker evidence |
| Full Redis process stop/restart | Not run; real key loss and injected publish failure were checked |
| Docker image build / Compose startup | Not run: Docker unavailable; CI and local commands supplied |
| Windows Docker Desktop / WSL2 execution | Instructions provided, not run in this Linux environment |
| GitHub Actions | Workflow supplied, not remotely executed |
| Native PostgreSQL benchmark | Script supplied; compatibility results must not be relabeled |
| Cloud deployment | Not attempted; local reproducibility is the priority |

The overall prompt's final acceptance criteria are therefore **not all verified**.
This deliverable is an implemented, compatibility-tested MVP with explicit native
release gates, not a claim of complete production acceptance. No reliability
percentage or unmeasured performance improvement is asserted.

## Reproduce the remaining gates

```bash
python scripts/init_env.py  # only if .env does not exist
pip install -e '.[dev]'
docker compose -p qm-tests -f compose.test.yml up -d --wait
python scripts/test_native.py
docker compose -p qm-tests -f compose.test.yml down -v
docker compose up -d --build --scale worker=3 --wait
python scripts/smoke.py
```

Then follow failure-recovery.md for Redis outage and crash demonstrations. Preserve
native test reports and benchmark environment details in your own commits before
claiming those results on a resume.
