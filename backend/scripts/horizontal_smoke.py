"""Horizontal-scale smoke test — Week 8.4.

Spawn N automation workers against the same Postgres, seed M no-op jobs,
let them race for a fixed duration, then assert correctness invariants:

  1. No double-execution — each job claimed exactly once (attempts == 1).
  2. NOTIFY fanout — workers wake within the wake budget after job creation.
  3. No deadlocks — all seeded jobs reach a terminal state before duration.
  4. Dead-letter rate == 0 for the seeded jobs.

Usage:
  python scripts/horizontal_smoke.py --workers 3 --jobs 20 --duration 60 --apply

Without --apply the script only prints what it would do (dry run).

Requires:
  TEST_POSTGRES_URL  — full DSN of a throwaway Postgres
  ALLOW_NOOP_SMOKE_JOBS=1 (auto-set for spawned workers)
"""
from __future__ import annotations

import argparse
import os
import platform
import signal
import subprocess
import sys
import time
from pathlib import Path

REPO_BACKEND = Path(__file__).resolve().parents[1]
SMOKE_COMPANY_ID = 999_999  # well above real-tenant range


def _seed_jobs(session, company_id: int, count: int) -> list[int]:
    from models.models import BackgroundJob, utc_now

    ids: list[int] = []
    now = utc_now()
    for _ in range(count):
        job = BackgroundJob(
            company_id=company_id,
            job_type="noop_smoke",
            status="pending",
            payload={"delay_ms": 50},
            run_after=now,
            created_at=now,
        )
        session.add(job)
        session.flush()
        ids.append(job.id)
    session.commit()
    return ids


def _spawn_worker(idx: int, dsn: str, company_id: int, log_dir: Path) -> subprocess.Popen:
    env = os.environ.copy()
    env["DATABASE_URL"] = dsn
    env["ALLOW_NOOP_SMOKE_JOBS"] = "1"
    env["RLS_WARN_ON_MISSING"] = "0"
    env["WORKER_LISTEN_NOTIFY"] = "1"
    log_path = log_dir / f"worker_{idx}.log"
    log_fh = log_path.open("w", buffering=1)
    cmd = [
        sys.executable,
        "-u",
        str(REPO_BACKEND / "run_automation_worker.py"),
        "--poll-interval",
        "2",
        "--company-id",
        str(company_id),
    ]
    proc = subprocess.Popen(
        cmd,
        cwd=str(REPO_BACKEND),
        env=env,
        stdout=log_fh,
        stderr=subprocess.STDOUT,
    )
    return proc


def _stop_worker(proc: subprocess.Popen, grace: float = 5.0) -> None:
    if proc.poll() is not None:
        return
    try:
        if platform.system() == "Windows":
            proc.terminate()
        else:
            proc.send_signal(signal.SIGTERM)
        proc.wait(timeout=grace)
    except subprocess.TimeoutExpired:
        proc.kill()
        try:
            proc.wait(timeout=2)
        except Exception:  # noqa: BLE001
            pass


def _all_terminal(session, ids: list[int]) -> bool:
    from sqlmodel import select
    from models.models import BackgroundJob

    statuses = session.exec(
        select(BackgroundJob.status).where(BackgroundJob.id.in_(ids))
    ).all()
    return bool(statuses) and all(s in ("done", "dead_letter") for s in statuses)


def _collect_metrics(session, ids: list[int]) -> dict:
    from sqlmodel import select
    from models.models import BackgroundJob

    rows = session.exec(
        select(BackgroundJob).where(BackgroundJob.id.in_(ids))
    ).all()
    by_status: dict[str, int] = {}
    multi_run = 0
    wake_lags_ms: list[float] = []
    for r in rows:
        by_status[r.status] = by_status.get(r.status, 0) + 1
        if r.attempts > 1:
            multi_run += 1
        if r.started_at and r.created_at:
            lag = (r.started_at - r.created_at).total_seconds() * 1000.0
            wake_lags_ms.append(lag)
    wake_lags_ms.sort()
    p95 = wake_lags_ms[int(0.95 * len(wake_lags_ms))] if wake_lags_ms else None
    return {
        "total": len(rows),
        "by_status": by_status,
        "multi_run": multi_run,
        "wake_lag_p50_ms": wake_lags_ms[len(wake_lags_ms) // 2] if wake_lags_ms else None,
        "wake_lag_p95_ms": p95,
        "wake_lag_max_ms": wake_lags_ms[-1] if wake_lags_ms else None,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workers", type=int, default=3)
    parser.add_argument("--jobs", type=int, default=20)
    parser.add_argument("--duration", type=int, default=60, help="Max seconds to wait for completion.")
    parser.add_argument("--wake-budget-ms", type=int, default=5000, help="p95 wake-lag budget.")
    parser.add_argument("--company-id", type=int, default=SMOKE_COMPANY_ID)
    parser.add_argument("--apply", action="store_true", help="Without this flag, dry-run only.")
    args = parser.parse_args()

    dsn = os.getenv("TEST_POSTGRES_URL") or os.getenv("DATABASE_URL")
    if not dsn or "postgres" not in dsn:
        print("ERROR: set TEST_POSTGRES_URL to a Postgres DSN.", file=sys.stderr)
        return 2

    if not args.apply:
        print(f"DRY RUN: would seed {args.jobs} jobs and spawn {args.workers} workers for {args.duration}s.")
        print(f"  DSN: {dsn.split('@')[-1] if '@' in dsn else dsn}")
        print("  Re-run with --apply to actually execute.")
        return 0

    sys.path.insert(0, str(REPO_BACKEND))
    os.environ["DATABASE_URL"] = dsn
    os.environ["RLS_WARN_ON_MISSING"] = "0"

    from sqlmodel import Session, delete
    from database import engine
    from models.models import BackgroundJob

    log_dir = REPO_BACKEND / "scripts" / "_smoke_logs"
    log_dir.mkdir(parents=True, exist_ok=True)

    print(f"[smoke] cleaning prior smoke rows for company={args.company_id}")
    with Session(engine) as s:
        s.exec(delete(BackgroundJob).where(BackgroundJob.company_id == args.company_id))
        s.commit()

    print(f"[smoke] seeding {args.jobs} noop_smoke jobs")
    with Session(engine) as s:
        ids = _seed_jobs(s, args.company_id, args.jobs)

    print(f"[smoke] spawning {args.workers} worker subprocesses (logs: {log_dir})")
    procs = [_spawn_worker(i, dsn, args.company_id, log_dir) for i in range(args.workers)]

    deadline = time.monotonic() + args.duration
    completed = False
    try:
        while time.monotonic() < deadline:
            with Session(engine) as s:
                if _all_terminal(s, ids):
                    completed = True
                    break
            time.sleep(1)
    finally:
        print(f"[smoke] stopping {len(procs)} workers")
        for p in procs:
            _stop_worker(p)

    with Session(engine) as s:
        m = _collect_metrics(s, ids)

    failures: list[str] = []
    if not completed:
        failures.append(f"jobs did not all reach terminal state in {args.duration}s; status={m['by_status']}")
    if m["multi_run"] > 0:
        failures.append(f"double-execution detected: {m['multi_run']} job(s) with attempts > 1")
    if (m["by_status"].get("dead_letter") or 0) > 0:
        failures.append(f"dead-letter rate > 0: {m['by_status']['dead_letter']} job(s)")
    if m["wake_lag_p95_ms"] is not None and m["wake_lag_p95_ms"] > args.wake_budget_ms:
        failures.append(f"wake p95 {m['wake_lag_p95_ms']:.0f}ms exceeds budget {args.wake_budget_ms}ms")

    print()
    print("=" * 60)
    print(f"workers      : {args.workers}")
    print(f"jobs         : {m['total']}")
    print(f"by_status    : {m['by_status']}")
    print(f"multi_run    : {m['multi_run']}")
    print(f"wake_lag_p50 : {m['wake_lag_p50_ms']!s} ms")
    print(f"wake_lag_p95 : {m['wake_lag_p95_ms']!s} ms")
    print(f"wake_lag_max : {m['wake_lag_max_ms']!s} ms")
    print("=" * 60)

    if failures:
        print("FAIL")
        for f in failures:
            print(f"  - {f}")
        return 1

    print("PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
