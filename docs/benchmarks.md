# Measured benchmark results

These are real measurements from the delivery run, not estimates or production
PostgreSQL capacity numbers. The database was **PGlite WASM through a socket proxy**
with a simple-query Psycopg adapter. Redis was native 7.0.15. API and worker processes
ran in the same restricted Linux runtime over loopback. Python: 3.12.14; kernel:
6.18.44; x86_64; host CPU/RAM allocation was not reliably exposed. Services shared
resources, so these runs are descriptive, not controlled hardware comparisons.

Workload: Fibonacci n=25; sequential HTTP submissions; normal priority; default
15-second lease, 1-second scheduler interval and 0.2-second worker polling. Each job
spawns a fresh Python child, so interpreter/import overhead dominates actual arithmetic.
One run per matrix cell; no warmup or confidence interval is claimed. Existing completed
history remained between runs, so these are not perfectly isolated scaling comparisons.

| Jobs | Workers | Elapsed s | Submit mean ms | Submit p95 ms | Jobs/s | Attempt mean s | Queue wait mean s | Completed | Failed |
|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 100 | 1 | 39.217 | 4.608 | 7.309 | 2.55 | 0.3813 | 19.3783 | 100 | 0 |
| 100 | 4 | 11.587 | 4.586 | 7.834 | 8.63 | 0.4264 | 5.418 | 100 | 0 |
| 1000 | 1 | 399.1 | 3.978 | 4.973 | 2.506 | 0.3896 | 196.5099 | 1000 | 0 |
| 1000 | 4 | 136.083 | 4.421 | 7.699 | 7.348 | 0.5275 | 65.707 | 1000 | 0 |

## Definitions and interpretation

Elapsed time starts before starting worker processes and includes HTTP submission,
queue waiting, child startup and completion detection. Throughput is submitted count
divided by that elapsed interval. Attempt duration is persisted start-to-completion
time, including child startup, not pure handler CPU time. Queue wait is first start
minus creation; all benchmark jobs completed in their initial attempts. Submission
p95 uses the sorted sample at floor(0.95 × (N−1)).

Across this matrix, all 2,200 jobs completed and zero entered FAILED. This is an
observed count, not a reliability percentage or guarantee. Four workers increased
throughput in these runs, but the single-backend database proxy and shared host prevent
extrapolating native PostgreSQL scaling or a million-job capacity.

A separate real worker-kill test measured **19.723 seconds** from supervisor kill to
replacement completion in the benchmark-associated test run. Its payload slept two
seconds; lease was 15 seconds, initial retry backoff two seconds. This is one recovery
sample, not a recovery SLA. The final test run may show another naturally varying
value in validation-run.log.

## Reproduction and raw evidence

- benchmark-results.json: machine-readable measurements and environment.
- benchmark-run.log: associated test output and printed benchmark records.
- scripts/benchmark.py: portable HTTP/process benchmark; accepts counts and workers.
- compatibility-runtime.md: optional reproduction of this restricted-host setup.

For native measurements, run PostgreSQL 16 and Redis 7, start only the API yourself,
and let the benchmark start its worker/scheduler processes. Use an idle disposable
stack and include exact CPU/RAM/container limits, versions and repetitions. Replace
these compatibility numbers only with actual newly measured native results.
