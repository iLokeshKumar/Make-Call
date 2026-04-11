from __future__ import annotations

import argparse
import logging
import time

from database import engine
from services.automation_worker_service import run_worker_cycle, run_worker_forever
from sqlmodel import Session

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
            # run_worker_forever only returns if it exits cleanly (shouldn't happen normally, but handle it gracefully).
            logger.warning("[supervisor] run_worker_forever returned unexpectedly – restarting")
            backoff = _BACKOFF_INITIAL_SECONDS  # reset: clean exit

        except Exception:  # noqa: BLE001
            logger.exception(
                "[supervisor] worker crashed (attempt #%d) – restarting in %ds",
                attempt,
                backoff,
            )
            time.sleep(backoff)
            backoff = min(backoff * 2, _BACKOFF_MAX_SECONDS)


if __name__ == "__main__":
    main()
