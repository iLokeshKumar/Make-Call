"""
Lightweight ASR cleanup runner.
Run this periodically (cron / scheduled task) to delete ASR segments older than `days`.
Usage: python scripts/asr_cleanup_runner.py [days]
"""
from datetime import datetime, timedelta
from decimal import Decimal
import sys

from sqlmodel import Session, select
from database import engine
from models.models import ASRSegment, ASRCleanupRun


def main():
    days = int(sys.argv[1]) if len(sys.argv) > 1 else 90
    cutoff = datetime.utcnow() - timedelta(days=days)
    start_ts = datetime.utcnow()
    with Session(engine) as session:
        rows = session.exec(select(ASRSegment).where(ASRSegment.created_at < cutoff)).all()
        count = len(rows)
        for r in rows:
            session.delete(r)
        session.commit()
    duration = (datetime.utcnow() - start_ts).total_seconds()
    print(f"Deleted {count} ASRSegment rows older than {days} days (duration: {duration:.2f}s)")

    # Record run
    try:
        with Session(engine) as s:
            run = ASRCleanupRun(
                company_id=None,
                run_at=datetime.utcnow(),
                cutoff_date=cutoff,
                deleted_count=count,
                duration_seconds=Decimal(str(duration)),
                success=True,
                error_text=None,
            )
            s.add(run)
            s.commit()
    except Exception as e:
        print(f"Failed to record ASR cleanup run: {e}")


if __name__ == '__main__':
    main()
