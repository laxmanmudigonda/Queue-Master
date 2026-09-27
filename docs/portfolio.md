# Portfolio materials

## GitHub description

A Python background-job engine with FastAPI, PostgreSQL leases, Redis priority delivery,
retries, crash recovery, idempotent submissions and execution history.

## Three resume bullet templates

Use these only after studying and reproducing the behavior. Replace the verbs with
“Extended an AI-assisted…” where that best describes your actual contribution.

- Developed and tested a FastAPI background-job service using PostgreSQL, SQLAlchemy
  and Redis, with six validated task types, scheduling, priority delivery and persistent
  execution history.
- Implemented lease-based worker ownership, bounded exponential retries and dead-letter
  recovery; exercised worker termination, stale completion rejection and idempotent
  submission/side-effect handling through automated tests.
- Packaged independent worker and scheduler processes with Alembic migrations, Docker
  Compose and GitHub Actions; built a repeatable benchmark and documented measured
  results and environment limitations.

Do not add a throughput number from the compatibility run as a production claim. Once
you run native tests, a suitable specific statement is “Verified X tests on PostgreSQL
16 and Redis 7,” where X is the actual result. Never state that skipped gates passed.

## LinkedIn project description

QueueMaster is a backend engineering project exploring what happens between accepting
a job and reliably finishing it. It uses FastAPI, PostgreSQL and Redis with independent
Python workers, expiring leases, retry backoff and a scheduler that reconstructs queue
state. A transactional counter example distinguishes duplicate submissions from
repeated execution and duplicate side effects.

The initial implementation was AI-assisted. My contribution is [describe your actual
changes, experiments and tests]. I focused on understanding failure boundaries and
recording what was verified rather than claiming exactly-once execution. Source,
architecture notes, tests and environment-qualified benchmark results are included.

## 3–5 minute demo script

**0:00–0:30 — Problem.** “A report request should return quickly while work continues
in the background. QueueMaster persists that request and gives it a trackable ID.”
Show README and Swagger at http://localhost:8000/docs.

**0:30–1:00 — Architecture.** Show the architecture diagram. Explain PostgreSQL as the
source of truth, Redis as a disposable ready index, and separate API/worker/scheduler
processes. State at-least-once semantics explicitly.

**1:00–1:40 — Submission and concurrency.** Enter the X-API-Key header in Swagger. Submit
Fibonacci n=25, retrieve its result (75025), then submit two long_running tasks with
seconds=3 while three workers are running. Show distinct worker IDs and overlapping
attempt times. Repeat an identical submission with Idempotency-Key and show one ID.

**1:40–2:15 — Retry.** Submit simulated_failure with failures=2 and max_retries=3.
Show attempts and RETRYING with future scheduled_at. After two failures, show the
third attempt succeeding. Submit failures=20, max_retries=0 to show dead-letter;
inspect its error and demonstrate the manual retry endpoint.

**2:15–3:10 — Crash.** Stop regular workers, run scripts/crash_demo.py with API and
scheduler still active. Explain the roughly 15-second default lease while waiting.
Show an abandoned first attempt and a completed replacement. Explain why an old token
cannot overwrite the new result and why an external API still needs idempotency.

**3:10–3:40 — Monitoring.** Open /api/v1/stats and /api/v1/workers. Explain that queue
depth is the Redis candidate count, pending includes delayed jobs, and active workers
are inferred from heartbeat freshness rather than process inspection.

**3:40–4:20 — Evidence.** Show test report and benchmark table. Identify the exact
runtime and any skipped native gates. If native verification is still pending, say
so. Explain that child startup dominates the tiny workload and propose one measured
improvement.

**4:20–4:40 — Your contribution.** Briefly state which parts you personally studied,
modified and reproduced. Credit the AI-assisted starting implementation honestly.

## Publishing to GitHub

Create an empty **public** repository called `queuemaster` on GitHub without
initializing a README. Review `git status --short`, then run from the project root:

```bash
git init
git add .
git status --short
# Confirm .env, credentials, local data and virtual environments are excluded.
git commit -m "Build QueueMaster API and operations dashboard"
git branch -M main
git remote add origin https://github.com/YOUR_USERNAME/queuemaster.git
git push -u origin main
```

The dashboard is at `http://localhost:8000/`. Before publishing, open it, enter
the local API key, submit a sample job, inspect its attempts, filter jobs and
verify worker heartbeat data. Add a real screenshot from that run to the README
if desired; never photograph or commit your `.env` key. A public GitHub repository
publishes source code, not a running dashboard: visitors can start it using Compose.
No remote repository was created or pushed by this delivery.
Include an attribution/contribution paragraph, add your own changes in separate
commits, and inspect the first CI run before adding a passing-build badge. Select a
license deliberately if you want others to reuse your code; no license is imposed here.
