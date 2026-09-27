# Reproducing the restricted-runtime checks

The delivery environment had no Docker and no usable non-root UID for native
PostgreSQL. Redis 7.0.15 ran from a locally extracted Ubuntu package. PostgreSQL SQL
compatibility checks used PGlite through its TCP socket proxy. Python processes used
a validation-only sitecustomize adapter to force Psycopg's simple-query ClientCursor;
the proxy's extended-protocol error handling caused failures without it. The production
application does not import this adapter and uses ordinary Psycopg connections.

The exact Node dependencies are locked in scripts/compatibility_runtime/package-lock.json.
Install Python development dependencies first. With Node 22+ and a redis-server
executable available, run from the repository root:

```bash
npm ci --prefix scripts/compatibility_runtime
python scripts/compatibility_runtime/run.py --redis-server /absolute/path/to/redis-server
# Include the 100/1000-job, 1/4-worker matrix:
python scripts/compatibility_runtime/run.py --redis-server /absolute/path/to/redis-server --benchmark
```

Ports 15432, 16379 and (for benchmarks) 8000 must be free. The harness uses a temporary
database and random API key, and stops its child services at exit. Do not export its
PYTHONPATH adapter into ordinary development or production. If Redis needs nonstandard
shared libraries, set LD_LIBRARY_PATH for that local executable before launching.

PGlite uses a single backend with multiplexed connections; it is not an alternative
proof of native PostgreSQL row-lock behavior or native database failure recovery.
Tests requiring those properties are explicitly skipped. Real Python worker processes,
real Redis operations and process-kill recovery still execute in this harness.

Primary reference: [PGlite socket documentation](https://pglite.dev/docs/pglite-socket).
The README warns about its single-connection multiplexing limitations. Treat the
benchmark numbers strictly as compatibility-runtime observations.
