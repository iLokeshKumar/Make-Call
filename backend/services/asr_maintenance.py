"""ASR maintenance background loop.
Runs periodically inside the FastAPI process to cleanup old ASRSegment rows.
Designed to be lightweight and safe for multi-tenant deletion.
"""
import asyncio
import os
import logging
from datetime import datetime, timedelta
from decimal import Decimal
from sqlmodel import Session, select
from database import engine
from models.models import ASRSegment, ASRCleanupRun

logger = logging.getLogger(__name__)

# Prometheus metrics
try:
    from prometheus_client import Counter, Gauge
    ASR_CLEANUP_RUNS = Counter("asr_cleanup_runs_total", "Total ASR cleanup runs", ["success"])
    ASR_CLEANUP_DELETED = Counter("asr_cleanup_deleted_total", "Total ASR rows deleted")
    ASR_CLEANUP_DURATION = Gauge("asr_cleanup_last_duration_seconds", "Duration of last ASR cleanup run in seconds")
except Exception:
    ASR_CLEANUP_RUNS = None
    ASR_CLEANUP_DELETED = None
    ASR_CLEANUP_DURATION = None

async def asr_cleanup_loop(days: int | None = None, interval_hours: int | None = None):
    """Periodic cleanup loop.
    - days: retention window in days (default from env ASR_CLEANUP_DAYS or 90)
    - interval_hours: how often to run (default env ASR_CLEANUP_INTERVAL_HOURS or 24)
    """
    days = days or int(os.getenv("ASR_CLEANUP_DAYS", "90"))
    interval_hours = interval_hours or int(os.getenv("ASR_CLEANUP_INTERVAL_HOURS", "24"))
    # Use engine provided by backend.database (shared SQLModel engine)
    interval_seconds = interval_hours * 3600

    logger.info("[ASR Maintenance] starting cleanup loop: retention=%sd interval=%sh", days, interval_hours)
    try:
        while True:
            try:
                cutoff = datetime.utcnow() - timedelta(days=days)
                deleted_total = 0
                start_ts = datetime.utcnow()
                with Session(engine) as session:
                    q = select(ASRSegment).where(ASRSegment.created_at < cutoff)
                    rows = session.exec(q).all()
                    deleted_total = len(rows)
                    for r in rows:
                        session.delete(r)
                    session.commit()
                duration = (datetime.utcnow() - start_ts).total_seconds()
                logger.info("[ASR Maintenance] cleanup run complete — deleted %d ASR rows older than %d days (%.2fs)", deleted_total, days, duration)

                # Record the run in ASRCleanupRun for monitoring
                try:
                    with Session(engine) as s:
                        run = ASRCleanupRun(
                            company_id=None,
                            run_at=datetime.utcnow(),
                            cutoff_date=cutoff,
                            deleted_count=deleted_total,
                            duration_seconds=Decimal(str(duration)),
                            success=True,
                            error_text=None,
                        )
                        s.add(run)
                        s.commit()
                except Exception:
                    logger.exception("[ASR Maintenance] failed to write cleanup run record")

                # Update Prometheus metrics if available
                try:
                    if ASR_CLEANUP_RUNS is not None:
                        ASR_CLEANUP_RUNS.labels(success="true").inc()
                    if ASR_CLEANUP_DELETED is not None:
                        ASR_CLEANUP_DELETED.inc(deleted_total)
                    if ASR_CLEANUP_DURATION is not None:
                        ASR_CLEANUP_DURATION.set(duration)
                except Exception:
                    logger.exception("[ASR Maintenance] failed to update Prometheus metrics")

            except Exception as exc:
                logger.exception("[ASR Maintenance] cleanup run failed: %s", exc)
                # attempt to record a failed run
                try:
                    with Session(engine) as s:
                        run = ASRCleanupRun(
                            company_id=None,
                            run_at=datetime.utcnow(),
                            cutoff_date=datetime.utcnow() - timedelta(days=days),
                            deleted_count=0,
                            duration_seconds=None,
                            success=False,
                            error_text=str(exc),
                        )
                        s.add(run)
                        s.commit()
                except Exception:
                    logger.exception("[ASR Maintenance] failed to write failed run record")

                # Update Prometheus metrics for failure
                try:
                    if ASR_CLEANUP_RUNS is not None:
                        ASR_CLEANUP_RUNS.labels(success="false").inc()
                except Exception:
                    logger.exception("[ASR Maintenance] failed to update Prometheus failure metric")

            # Sleep until next run or exit when cancelled
            try:
                await asyncio.sleep(interval_seconds)
            except asyncio.CancelledError:
                logger.info("[ASR Maintenance] cancelled, exiting loop")
                break
    except asyncio.CancelledError:
        logger.info("[ASR Maintenance] loop cancelled")
    except Exception:
        logger.exception("[ASR Maintenance] unexpected error — exiting")
    finally:
        logger.info("[ASR Maintenance] stopped")
