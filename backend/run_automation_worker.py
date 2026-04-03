from __future__ import annotations

import argparse
import logging
import time

from services.automation_worker_service import run_worker_cycle, run_worker_forever
from database import engine
from sqlmodel import Session

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)


def main() -> None:
    parser = argparse.ArgumentParser(description="Run queued call tasks and due campaign steps.")
    parser.add_argument("--once", action="store_true", help="Run a single worker cycle and exit.")
    parser.add_argument("--company-id", type=int, default=None, help="Restrict processing to one company.")
    parser.add_argument("--poll-interval", type=int, default=60, help="Seconds between worker cycles.")
    parser.add_argument("--dial-limit", type=int, default=20, help="Max queued call tasks to start per company per cycle.")
    args = parser.parse_args()

    if args.once:
        with Session(engine) as session:
            result = run_worker_cycle(
                session=session,
                company_id=args.company_id,
                dial_limit_per_company=args.dial_limit,
            )
            print(result)
        return

    # Process supervision: restart worker loop if it crashes unexpectedly.
    backoff_seconds = 5
    while True:
        try:
            run_worker_forever(
                poll_interval_seconds=args.poll_interval,
                company_id=args.company_id,
                dial_limit_per_company=args.dial_limit,
            )
        except Exception as exc:
            logger.exception("Automation worker crashed, restarting in %s seconds", backoff_seconds)
            time.sleep(backoff_seconds)
            backoff_seconds = min(backoff_seconds * 2, 60)
        else:
            backoff_seconds = 5



if __name__ == "__main__":
    main()
