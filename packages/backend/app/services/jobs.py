"""Background job execution with retry and dead letter support."""
import json
import time
import logging
from datetime import datetime
from ..extensions import db
from ..models import JobRecord

logger = logging.getLogger("finmind.jobs")

MAX_BACKOFF_SECONDS = 30


def get_backoff_delay(retry_count: int) -> int:
    """Exponential backoff: 2^retry seconds, capped at 30s."""
    delay = 2 ** (retry_count + 1)
    return min(delay, MAX_BACKOFF_SECONDS)


def execute_job(job: JobRecord, fn, *args, **kwargs):
    """Execute a job function with retry logic.

    Attempts the function up to max_retries times.
    On success: marks job as completed.
    On failure with retries remaining: retries with exponential backoff.
    On failure after max retries: marks job as dead_letter.
    """
    job.status = "running"
    job.updated_at = datetime.utcnow()
    db.session.commit()

    last_exception = None
    for attempt in range(job.max_retries):
        try:
            result = fn(*args, **kwargs)
            job.status = "completed"
            job.retry_count = attempt
            job.last_error = None
            job.updated_at = datetime.utcnow()
            db.session.commit()
            logger.info("Job %s completed after %d attempt(s)", job.id, attempt + 1)
            return result
        except Exception as e:
            last_exception = str(e)
            job.retry_count = attempt + 1
            job.last_error = last_exception
            job.updated_at = datetime.utcnow()
            db.session.commit()
            logger.warning(
                "Job %s attempt %d failed: %s", job.id, attempt + 1, last_exception
            )
            if attempt < job.max_retries - 1:
                delay = get_backoff_delay(attempt)
                time.sleep(delay)

    job.status = "dead_letter"
    job.updated_at = datetime.utcnow()
    db.session.commit()
    logger.error("Job %s moved to dead_letter after %d retries", job.id, job.max_retries)
    raise RuntimeError(f"Job failed after {job.max_retries} retries: {last_exception}")
