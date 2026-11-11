"""Standalone background worker.

Usage (from ``backend/``)::

    python -m app.worker               # loop forever
    python -m app.worker --once        # drain currently queued jobs and exit
    python -m app.worker --max-jobs 1  # bounded batch

Workers claim jobs atomically (status QUEUED -> CLAIMED) before execution, so
multiple worker processes can run against PostgreSQL without double processing.
SQLite deployments should use a single worker; the claim still guards against
races, but SQLite serializes writers anyway.

Stale claims (crashed workers) are returned to QUEUED after
``WORKER_STALE_MINUTES``. This is deliberately conservative: a job running
longer than that threshold must be inspected before it is retried.
"""
from __future__ import annotations

import argparse
import logging
import signal
import time
from datetime import timedelta

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.config import get_settings
from app.core.provenance import utcnow
from app.db.models import ProcessingJob
from app.db.session import init_db, session_scope
from app.logging_config import configure_logging
from app.processing.engine import execute_job

logger = logging.getLogger("sarvex.worker")

NON_TERMINAL = (
    "CLAIMED",
    "VALIDATING",
    "DOWNLOADING",
    "PREPROCESSING",
    "PROCESSING",
    "ANALYZING",
    "POSTPROCESSING",
)


def recover_stale_jobs(session: Session, stale_minutes: int) -> list[str]:
    cutoff = utcnow() - timedelta(minutes=max(stale_minutes, 1))
    stale = session.scalars(
        select(ProcessingJob).where(
            ProcessingJob.status.in_(NON_TERMINAL),
            ProcessingJob.started_at.is_not(None),
            ProcessingJob.started_at < cutoff,
        )
    ).all()
    requeued: list[str] = []
    for job in stale:
        job.status = "QUEUED"
        job.current_stage = "QUEUED"
        job.progress = 0.0
        job.started_at = None
        job.error = None
        job.logs = list(job.logs or []) + [
            {
                "ts": utcnow().isoformat(),
                "level": "WARNING",
                "message": (
                    f"Stale execution recovered after {stale_minutes} minutes; "
                    "job returned to QUEUED"
                ),
            }
        ]
        requeued.append(job.id)
    if requeued:
        session.commit()
        logger.warning("Recovered %s stale job(s): %s", len(requeued), requeued)
    return requeued


def claim_jobs(session: Session, limit: int) -> list[str]:
    candidates = session.scalars(
        select(ProcessingJob.id)
        .where(ProcessingJob.status == "QUEUED")
        .order_by(ProcessingJob.queued_at)
        .limit(limit)
    ).all()
    claimed: list[str] = []
    for job_id in candidates:
        result = session.execute(
            update(ProcessingJob)
            .where(ProcessingJob.id == job_id, ProcessingJob.status == "QUEUED")
            .values(
                status="CLAIMED",
                current_stage="CLAIMED",
                progress=2.0,
                started_at=utcnow(),
                error=None,
            )
        )
        if result.rowcount == 1:
            claimed.append(job_id)
    session.commit()
    return claimed


def process_once(max_jobs: int = 10, *, recover: bool = True) -> int:
    """Claim and run up to ``max_jobs`` queued jobs. Returns execution count."""
    settings = get_settings()
    executed = 0
    with session_scope() as session:
        if recover:
            recover_stale_jobs(session, settings.worker_stale_minutes)
        claimed = claim_jobs(session, max_jobs)
    for job_id in claimed:
        logger.info("Executing job %s", job_id)
        try:
            status = execute_job(job_id, claimed=True)
            logger.info("Job %s finished with status %s", job_id, status)
        except Exception:  # noqa: BLE001 - one job must not kill the worker
            logger.exception("Worker crashed while executing job %s", job_id)
            with session_scope() as session:
                job = session.get(ProcessingJob, job_id)
                if job and job.status not in {"COMPLETED", "FAILED", "CANCELLED"}:
                    job.status = "FAILED"
                    job.current_stage = "FAILED"
                    job.error = "Worker exception; see worker logs"
                    job.finished_at = utcnow()
        executed += 1
    return executed


def run_forever(poll_seconds: float, max_jobs: int) -> None:
    stopping = False

    def _stop(signum, frame):  # type: ignore[no-untyped-def]
        nonlocal stopping
        stopping = True
        logger.info("Shutdown signal %s received; finishing current batch", signum)

    try:
        signal.signal(signal.SIGINT, _stop)
        signal.signal(signal.SIGTERM, _stop)
    except (ValueError, AttributeError):  # pragma: no cover - non-main thread
        pass
    while not stopping:
        try:
            executed = process_once(max_jobs)
        except Exception:  # noqa: BLE001 - keep the worker alive
            logger.exception("Worker poll failed")
            executed = 0
        if executed == 0:
            time.sleep(max(poll_seconds, 0.2))
    logger.info("Worker stopped")


def main() -> None:
    settings = get_settings()
    parser = argparse.ArgumentParser(description="SARVEX background processing worker")
    parser.add_argument("--once", action="store_true", help="drain queued jobs and exit")
    parser.add_argument("--max-jobs", type=int, default=10, help="jobs per polling batch")
    parser.add_argument(
        "--poll",
        type=float,
        default=settings.worker_poll_seconds,
        help="seconds between polls when idle",
    )
    parser.add_argument(
        "--no-recover",
        action="store_true",
        help="do not requeue stale in-progress jobs at startup",
    )
    args = parser.parse_args()

    configure_logging(settings.log_level, settings.structured_logs)
    logger.info(
        "Worker starting (database=%s, sqlite=%s, max_jobs=%s)",
        "postgresql" if not settings.using_sqlite else "sqlite",
        settings.using_sqlite,
        args.max_jobs,
    )
    init_db()
    try:
        from app.ml.registry import get_model_registry

        with session_scope() as session:
            get_model_registry().sync_to_db(session)
    except Exception:  # noqa: BLE001
        logger.exception("Model registry sync failed in worker")

    if args.once:
        executed = process_once(args.max_jobs, recover=not args.no_recover)
        logger.info("Worker drained %s job(s)", executed)
        return
    run_forever(args.poll, args.max_jobs)


if __name__ == "__main__":
    main()
