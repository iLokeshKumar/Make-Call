from __future__ import annotations

import argparse
import logging
import time

# Windows: switch to the Selector event-loop policy BEFORE any async code or
# psycopg import. Otherwise psycopg's async connection pool (the LangGraph
# AsyncPostgresSaver checkpointer used during pre-call research) fails with
# "Psycopg cannot use the 'ProactorEventLoop'" on every pool open — which also
# makes the 15s pre-call KB budget time out. Same fix as backend/main.py.
from win_async_fix import apply_windows_async_fix

apply_windows_async_fix()

from database import engine, init_db
from services.automation_worker_service import run_worker_cycle, run_worker_forever
from sqlmodel import Session
from sqlalchemy import inspect as _sa_inspect
from sqlalchemy.exc import OperationalError, ProgrammingError

logger = logging.getLogger(__name__)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)

# Supervisor constants
_BACKOFF_INITIAL_SECONDS = 5
_BACKOFF_MAX_SECONDS = 60


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Automation worker – runs queued call tasks and due campaign steps."
    )
    parser.add_argument(
        "--once",
        action="store_true",
        help="Run a single worker cycle then exit (useful for cron / debugging).",
    )
    parser.add_argument(
        "--company-id",
        type=int,
        default=None,
        help="Restrict processing to a single company.",
    )
    parser.add_argument(
        "--poll-interval",
        type=int,
        default=60,
        help="Seconds to sleep between worker cycles (default: 60).",
    )
    parser.add_argument(
        "--dial-limit",
        type=int,
        default=20,
        help="Max queued call tasks to start per company per cycle (default: 20).",
    )
    args = parser.parse_args()

    # Ensure schema exists. If the worker runs before the API server has
    # initialised the database, every query would fail with UndefinedTable
    # and the supervisor would spin forever logging the same traceback.
    # We do NOT catch exceptions here: a DB that is unreachable or has the
    # wrong credentials must fail loudly at startup, not silently inside a
    # restart loop.
    existing = set(_sa_inspect(engine).get_table_names())
    if "users" not in existing:
        logger.warning(
            "[supervisor] schema missing (no 'users' table) - running init_db()"
        )
        init_db()
        logger.info("[supervisor] init_db() complete")

    if args.once:
        # Single-shot mode – run one cycle and print the result.
        logger.info("[supervisor] running in --once mode")
        with Session(engine) as session:
            result = run_worker_cycle(
                session=session,
                company_id=args.company_id,
                dial_limit_per_company=args.dial_limit,
            )
        print(result)
        return

    # Continuous mode: process supervision with exponential back-off. If run_worker_forever raises (e.g. DB connection lost), the supervisor logs the crash, waits with exponential back-off, then restarts it. Back-off resets to initial value after a successful run so transient failures don't permanently slow the worker.
    backoff = _BACKOFF_INITIAL_SECONDS
    attempt = 0

    logger.info(
        "[supervisor] starting continuous worker | poll_interval=%ds | dial_limit=%d | company_id=%s",
        args.poll_interval,
        args.dial_limit,
        args.company_id,
    )

    while True:
        attempt += 1
        logger.info("[supervisor] worker attempt #%d", attempt)
        try:
            run_worker_forever(
                poll_interval_seconds=args.poll_interval,
                company_id=args.company_id,
                dial_limit_per_company=args.dial_limit,
            )
            
            logger.warning("[supervisor] run_worker_forever returned unexpectedly – restarting")
            backoff = _BACKOFF_INITIAL_SECONDS  # reset: clean exit

        except (ProgrammingError, OperationalError):
            # Schema missing, bad credentials, DB unreachable -> not something
            # a restart loop can fix. Fail fast with a non-zero exit so the
            # process manager (systemd, supervisord, Conductor) escalates
            # instead of burning CPU on a hopeless retry.
            logger.exception(
                "[supervisor] fatal database error - aborting. "
                "Check DATABASE_URL, that Postgres is reachable, and that "
                "migrations have run."
            )
            raise SystemExit(2)
        except KeyboardInterrupt:
            logger.info("[supervisor] interrupted - exiting cleanly")
            return
        except Exception:
            # Transient failures (network, lock contention, etc.) - log full
            # traceback and back off. We never swallow silently.
            logger.exception(
                "[supervisor] worker crashed (attempt #%d) - restarting in %ds",
                attempt,
                backoff,
            )
            time.sleep(backoff)
            backoff = min(backoff * 2, _BACKOFF_MAX_SECONDS)


if __name__ == "__main__":
    main()
