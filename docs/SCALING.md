# Horizontal Scaling — Multi-worker Safety

The automation worker uses Postgres advisory locks per company so multiple
worker processes can run against the same database without claiming the same
job twice. `services/notify_listener.py` wakes idle workers within ~milliseconds
of a new task via `LISTEN/NOTIFY`. Polling is the safety net.

`backend/scripts/horizontal_smoke.py` proves these invariants under
contention.

## What it asserts

1. **No double-execution** — every seeded job has `attempts == 1` after the run.
   Proves the per-company `pg_advisory_lock` + the `status='running'` claim
   transaction together prevent two workers from grabbing the same row.
2. **NOTIFY wake budget** — p95 of `started_at - created_at` is below
   `--wake-budget-ms` (default 5000ms). With `WORKER_LISTEN_NOTIFY=1` this
   is usually < 100ms.
3. **No deadlocks** — every job reaches `done` or `dead_letter` before
   `--duration` elapses. A stuck `pg_try_advisory_lock` would leave jobs
   in `pending` past the deadline.
4. **Dead-letter rate == 0** — the `noop_smoke` executor cannot fail, so
   any `dead_letter` row is a real bug.

## Running it

Requirements:

- A throwaway Postgres reachable as `TEST_POSTGRES_URL` (do **not** point at
  prod — the script seeds and deletes rows in `background_jobs` for company
  id `999999`).
- `ALLOW_NOOP_SMOKE_JOBS=1` is exported automatically into the spawned
  worker subprocesses; the parent script also needs it on import.

```bash
export TEST_POSTGRES_URL="postgresql://user:pw@localhost:5432/rio_smoke"
export ALLOW_NOOP_SMOKE_JOBS=1

cd backend
python scripts/horizontal_smoke.py --workers 3 --jobs 20 --duration 60 --apply
```

Without `--apply` you get a dry-run summary. The exit code is `0` on PASS,
`1` on FAIL, `2` on misconfiguration.

## Reading the report

```
============================================================
workers      : 3
jobs         : 20
by_status    : {'done': 20}
multi_run    : 0
wake_lag_p50 : 42.0 ms
wake_lag_p95 : 180.0 ms
wake_lag_max : 220.0 ms
============================================================
PASS
```

- `multi_run > 0` → the advisory lock or the claim transaction is broken.
- `by_status` containing `pending` after duration → workers didn't wake or
  deadlocked. Inspect `backend/scripts/_smoke_logs/worker_*.log`.
- `wake_lag_p95` rising over time → NOTIFY connection is dropping; check
  `notify_listener` reconnect logic.

## Pytest wrapper

`backend/test/test_worker_horizontal.py` runs the same script via pytest
with a 45s duration. Skipped by default.

```bash
TEST_POSTGRES_URL=postgresql://... \
FORCE_HORIZONTAL_SMOKE=1 \
    pytest test/test_worker_horizontal.py -q
```

## Windows quirk

`subprocess.Popen` + Postgres connection ownership is unreliable on Windows
when the parent dies before the child cleans up its connection. The pytest
wrapper skips on Windows unless `FORCE_HORIZONTAL_SMOKE=1` is set. CI on
Linux runs it on demand.

## Tearing down

The script cleans up its own seed rows on each run, so re-running is safe.
If a worker subprocess gets orphaned (Ctrl-C during the test, OS scheduler
weirdness), check `ps aux | grep run_automation_worker` and SIGKILL stragglers
manually.
