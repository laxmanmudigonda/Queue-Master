# QueueMaster: placement interview preparation

## A 90-second explanation

“QueueMaster separates accepting work from executing it. A FastAPI endpoint validates
a registered task and commits a job to PostgreSQL. Redis holds a priority-sorted ready
index. Independent Python workers pop candidates and atomically claim due pending
rows using PostgreSQL row locks. Each claim creates an attempt and an expiring lease.
The supervisor runs the task in a child process while renewing ownership. It commits
the result only if its lease is still valid. A separate scheduler publishes delayed
jobs, rebuilds missing Redis entries and recovers expired leases. Failed tasks use
bounded exponential backoff and eventually enter a queryable dead-letter state.
The guarantee is at-least-once processing, so the project separately demonstrates
submission idempotency and transactional side-effect deduplication.”

Say “I studied/implemented/changed/tested” only for work you actually did. This initial
implementation was AI-assisted. Explain the code, reproduce its tests and make your
own changes before presenting ownership. Native Docker acceptance remains a separate
gate until you run it; never replace that caveat with a reliability percentage.

## Questions and answers

### 1. Why use a message queue?

An HTTP request should not stay open while a report runs. Queuing lets the API persist
intent and return a job ID quickly; clients poll for completion. Producers and workers
can scale independently, and a backlog absorbs bursts. The trade-off is eventual
completion: acceptance does not mean success, and clients need states, retry handling
and visibility into failures. A queue does not create unlimited capacity; arrival rate
must eventually remain below sustainable service rate or backlog keeps growing.

### 2. Why Redis?

Redis offers simple atomic sorted-set operations and fast access to candidate IDs.
`ZADD` naturally deduplicates a job ID, while `ZPOPMIN` retrieves the lowest priority
score atomically. Here Redis is a coordination accelerator, not durable authority.
Using Redis alone would require a different durability/recovery design. Its failure
pauses dispatch but does not delete the committed PostgreSQL job records.

### 3. Why PostgreSQL?

The project needs transactions, relational history, uniqueness and row locks. A claim
updates the job and adds its attempt in one transaction. A unique idempotency key
arbitrates competing submissions. Foreign keys preserve relationships, while indexed
state/time queries drive recovery. PostgreSQL is also an operational cost and a
throughput bottleneck; the design pays that cost to make state transitions reliable
and inspectable.

### 4. What makes this a distributed system?

API, scheduler, workers, Redis and PostgreSQL run as independently failing components
and communicate across process/network boundaries. Even on one laptop, requests can
time out, processes can die and a response can be lost after a commit. There is no
single atomic transaction spanning Python execution, Redis and PostgreSQL. The system
therefore uses durable intent, leases, idempotency and reconciliation to manage partial
failure rather than assuming every operation succeeds together.

### 5. What is a process versus a thread?

Processes have separate memory/address spaces and communicate explicitly. Threads
share a process's memory, making communication cheap but shared mutation hazardous.
QueueMaster workers are independent processes; task execution is in a spawned child.
This isolates task execution from the supervisor's lease loop and allows CPU work in
separate interpreters. Processes cost more startup time and memory. FastAPI can still
use a thread pool for synchronous endpoint functions without those threads being job
workers.

### 6. What is concurrency?

Concurrency means multiple tasks are in progress during overlapping intervals. They
might alternate on one CPU while waiting for I/O. Two workers sleeping on two jobs
are concurrent even if the host has only one core. The overlap test compares start and
completion timestamps and distinct worker IDs; it does not claim a particular amount
of CPU parallelism or a linear speedup.

### 7. What is parallelism?

Parallelism means executing operations at the same time on different processing
resources. Multiple Python processes can use multiple CPU cores and avoid one
interpreter's GIL limiting CPU-bound Python threads. Available cores and workload
matter: the demonstration Fibonacci calculation is small, so process startup, database
round trips and polling can dominate. Increasing workers does not prove the system
scales linearly.

### 8. What is a race condition here?

A race occurs when correctness depends on the timing of competing operations. Two
workers could both read PENDING and both write RUNNING if those actions were separate
unprotected steps. Another race is two API requests checking an idempotency key before
either inserts it. QueueMaster uses row locks for claims and a database unique
constraint for submission identity; application-level “check then insert” alone is
insufficient.

### 9. What is an atomic operation?

An atomic operation has an indivisible externally observed effect within its stated
boundary. Redis ZPOPMIN atomically chooses and removes a member. A PostgreSQL
transaction atomically commits job state and attempt history. Neither operation makes
the full workflow atomic: a crash can happen after Redis pop but before the database
claim. The scheduler repairs that cross-system gap.

### 10. How does a worker claim a job?

It pops a Redis candidate, opens a DB transaction and selects that ID only if it is
pending and due, using FOR UPDATE SKIP LOCKED. It sets RUNNING, increments the attempt
number, creates a new ownership token and expiry, records the worker ID, and inserts
an attempt. The transaction commits before execution. The lock is short-lived;
keeping it open during a multi-minute task would harm concurrency and recovery.

### 11. What happens if two workers claim simultaneously?

On native PostgreSQL, one obtains the row lock. The other skips the locked row, or sees
the committed RUNNING state and rejects it. Redis normally hands one candidate to one
worker, but the database remains authoritative because the scheduler can republish an
ID concurrently. The native test races eight claims and expects exactly one valid
claim. PGlite's single-backend proxy cannot establish this production locking property.

### 12. What is a processing lease?

A lease is temporary permission to own a job, represented by a token and expiration.
The owner must renew it before expiration. A heartbeat reports worker activity, but
recovery examines each job's lease, not just a worker's last heartbeat. This distinction
avoids treating a generally alive worker as proof that every task it ever owned is
healthy. Lease length balances fast recovery against false expiry during pauses.

### 13. How does crash recovery work?

The scheduler locks expired RUNNING rows in batches. It marks the attempt abandoned,
records an error and checks the remaining retry budget. With budget, the job returns
to pending with a future backoff time; otherwise it becomes failed. Once due, the ready
index is rebuilt. The next worker receives a new token and attempt. Recovery latency
includes remaining lease, scheduler interval, backoff, waiting and execution.

### 14. What prevents a stale worker from corrupting a result?

Completion checks the job's current status, token and expiration under a row lock.
If recovery replaced ownership, the old token no longer matches; even before recovery,
an already expired token cannot commit completion. This protects QueueMaster state.
It does not stop an old process from physically running or calling an external API.
External effects need receiver-enforced idempotency or fencing support of their own.

### 15. What is at-least-once delivery?

Work may be attempted more than once because the system retries ambiguous failures.
A handler might finish just before its worker crashes, leaving no recorded success.
Retrying avoids silently losing that work, at the cost of duplicates. This guarantee
assumes the database remains durable and services eventually recover. With finite
retry budgets, a job can reach dead-letter instead of successfully completing.
Exactly-once execution is not claimed.

### 16. How does submission idempotency work?

The caller supplies Idempotency-Key. A unique DB constraint permits only one job for
that key. A normalized request hash is stored with the first job. A repeated matching
request returns the same ID, including its current status; different content gets
409. The key is global within this single-application MVP, not scoped to a tenant.
Keys have no expiry because deleting them prematurely could allow old retries to
create duplicate jobs.

### 17. How does the counter tolerate duplicate execution?

The handler locks the job row and looks for a durable effects receipt. If one exists,
it returns that receipt. Otherwise it increments a named counter using an UPSERT and
inserts the receipt in the same transaction. A crash before commit changes neither;
a crash after commit lets retry observe the receipt. The lock serializes the same job,
and the counter update safely serializes different jobs sharing a counter name.

### 18. How do retries work?

An attempt failure consumes one execution attempt. If the attempt's position in its
current budget is at most max_retries, the service records RETRYING and a future due
time. The scheduler later moves it to PENDING. With max_retries=3, execution can occur
four times. Manual retry is permitted only from FAILED, resets the budget base and
keeps lifetime attempt history. The sample failure handler compares its configured
failure count to the lifetime attempt number.

### 19. Why exponential backoff?

A failing dependency may need time to recover. Immediate retries can amplify load
and cause a retry storm. Delays grow 2, 4, 8 seconds with the defaults, capped at 60.
This reduces repeated pressure but increases completion latency. Random jitter would
help many jobs avoid synchronizing at the same delay; it is not implemented in this
MVP and should not be claimed in an interview.

### 20. What is a dead-letter queue?

It is a place to inspect work that exhausted automatic attempts. Here it is represented
by durable FAILED rows and a filtered API rather than a separate Redis list. That
keeps payload, reason, attempts and events together. Operators can inspect and manually
retry a failed job. Dead-letter does not mean data was deleted, nor does it automatically
mean the handler made no external changes.

### 21. What happens if Redis crashes?

Workers temporarily cannot retrieve candidates, but job rows survive in PostgreSQL.
The scheduler republishes due pending IDs once Redis becomes available. Running workers
can complete using the DB without a Redis completion acknowledgment. Readiness becomes
unhealthy during the outage. This approach deliberately trades repeated scanning and
possible duplicate candidates for a small, understandable recovery mechanism.

### 22. What happens if PostgreSQL crashes?

New durable submissions and claims cannot proceed. The API returns 503 for DB errors;
workers/scheduler back off and reconnect using the connection pool. Active work may
lose its lease and be retried after service recovery. A lost response can leave commit
status uncertain, so blindly assuming rollback is wrong. Backups, WAL durability and
restore procedures are outside this MVP; queue logic cannot recover a destroyed source
of truth.

### 23. Why not make Redis and PostgreSQL one transaction?

Ordinary Redis and PostgreSQL commands do not share a distributed ACID transaction.
Trying to coordinate them adds complexity and failure modes. This project commits the
database first and reconciles Redis afterward. An alternative transactional outbox
would store publication intent in the same DB transaction and have a dispatcher deliver
it. An outbox can reduce full scans, but consumers still need duplicate handling.

### 24. How are delayed jobs implemented?

The database stores scheduled_at with a timezone. Claim rejects jobs whose due time is
in the future. The scheduler publishes eligible rows when their time arrives. Retries
use the same due-time mechanism. Delayed jobs stay PENDING until claimed; a pending
count therefore includes scheduled future work. Actual execution can be later than the
scheduled time because of polling, backlog, priority and worker availability.

### 25. How would you scale this system?

First measure bottlenecks and separate worker types by workload. Add workers until
DB contention, CPU or another dependency becomes limiting. Then replace full ready
reconciliation with more selective durable publication, add retention/archival, batch
operations, and partition queues by tenant or workload. Preserve claim and recovery
invariants during every change. Scaling the API alone cannot increase processing
throughput if workers or the database are already saturated.

### 26. What are its current bottlenecks?

Each task spawns a fresh interpreter, making tiny jobs expensive. Each attempt requires
multiple database transactions and heartbeat writes. Scheduler scans grow with ready
backlog; statistics aggregate entire tables. Polling adds idle latency. Results and
history accumulate without retention. The recorded compatibility benchmark measures
all these plus a PGlite proxy, so it is evidence about that run rather than a native
production capacity claim.

### 27. How would you handle one million jobs?

I would not extrapolate the small benchmark. I would generate representative payloads,
measure arrival rate and latency distribution, size DB/Redis memory and storage, and
load-test retention and recovery. Likely changes include an outbox, partitioned queues,
keyset pagination, rollup metrics, batched dispatch, worker pools, object storage results,
and history archival. I would also test outages at backlog scale because rebuilding
one million ready entries is materially different from recovering a handful.

### 28. How is this different from Celery?

Celery is a mature ecosystem with brokers, routing, execution pools and extensive
configuration. QueueMaster implements a deliberately small subset so its coordination
logic can be studied: SQL claims, lease renewal, recovery, backoff and idempotency.
It is not a drop-in replacement and lacks many operational features. Choosing Celery
for a real product can be sensible; the educational value here is understanding the
mechanisms rather than rebranding an existing framework.

### 29. What does ACID mean in this project?

Atomicity keeps job transitions and attempt records together. Consistency includes
constraints and application state rules. Isolation ensures competing claims interact
through locks rather than racing unchecked. Durability means committed records survive
supported DB failures, subject to database configuration and storage guarantees.
ACID does not extend to external effects or Redis publication automatically, which is
why recovery and idempotency remain necessary.

### 30. How would you diagnose a stuck job?

Inspect status, scheduled_at, lease expiry, last attempt, worker heartbeat and events.
A future due time is not stuck. A valid running lease means a worker still claims
ownership; an expired one suggests checking scheduler health. For a pending due job,
check Redis availability and scheduler publication. For repeated failure, examine the
bounded error history and payload without logging secrets. Dead-letter can be a
correct outcome rather than a queue malfunction.

### 31. How are the APIs secured?

All job, worker and statistics routes require a constant-time-checked API key from
environment configuration. Payloads pass registered Pydantic models and a bounded
request body. Users cannot submit arbitrary Python code or shell commands. SQLAlchemy
parameterizes database operations. This does not supply per-user access control,
TLS, rate limiting or secret rotation. Public health endpoints expose only coarse
status, while OpenAPI describes the contract.

### 32. What did the tests actually prove?

Unit tests verify validation, task outputs, retry math and the transition matrix.
Integration tests exercise committed state, API behavior, Redis, duplicate candidates,
actual child execution and process-kill recovery. Overlap tests demonstrate independent
workers progress concurrently. Native lock races and backend-termination checks need
native PostgreSQL; skipped tests are not evidence. A passing finite test suite also
cannot prove that no distributed race remains.

### 33. How should performance be reported?

State workload, database/runtime, worker count, submission method, payload size and
measurement interval. Report submission mean/p95, completed count, elapsed throughput,
attempt duration and queue wait. QueueMaster's elapsed interval starts before worker
startup and submission, so throughput includes those costs. Attempt duration includes
child startup, not just Fibonacci CPU time. One run is descriptive, not statistically
stable; repeat representative native runs before making resume-scale claims.

### 34. Why does a health check differ from readiness?

Liveness asks whether the process can respond. Readiness asks whether dependencies
needed for normal operation are reachable. Restarting an otherwise healthy API every
time Redis is briefly unavailable can make an outage worse. QueueMaster exposes both.
A DB ping alone does not prove the correct schema is present; migrations must finish
before application startup, which Compose enforces with a migration service.

### 35. What would you improve first?

After native verification, I would choose an improvement supported by measurement:
a reusable supervised execution pool for tiny-job overhead, retry jitter to avoid
synchronized retries, or an outbox for publication scan cost. I would add a focused
regression test and compare before/after on the same workload. That gives a concrete,
honest independent contribution and a useful interview discussion about trade-offs.

## Study and ownership plan

Week 1: trace a submission through API, schema and migration; add one validated task
with tests. Week 2: draw competing claim transactions and reproduce native concurrency
tests. Week 3: run crash/Redis experiments, explain an ambiguous commit and implement
one reliability improvement. Week 4: benchmark on your machine, publish measured
results, record the demo and write a contribution note listing your own changes.
