"""Application service for creating and enqueueing API transfer jobs.

HTTP parsing and response formatting stay in api_views; this module owns
persistence, idempotent reuse of active jobs, and Celery dispatch.
"""
from django.db import IntegrityError, transaction

from ..models import OAuthCredential, TransferJob
from .transfer_dispatch import dispatch_transfer_job

logger = logging.getLogger(__name__)


def create_or_reuse_transfer_job(*, session_fingerprint, source_url, target_playlist=""):
    """Return (job, HTTP status, optional error message)."""
    active = TransferJob.objects.filter(
        session_fingerprint=session_fingerprint,
        status__in=[TransferJob.Status.QUEUED, TransferJob.Status.RUNNING],
    ).first()
    if active:
        return active, 202, None

    try:
        with transaction.atomic():
            job = TransferJob.objects.create(
                session_fingerprint=session_fingerprint,
                source_url=source_url,
                target_playlist=target_playlist,
            )
    except IntegrityError:
        # The database constraint is the final guard against concurrent POSTs.
        active = TransferJob.objects.filter(
            session_fingerprint=session_fingerprint,
            status__in=[TransferJob.Status.QUEUED, TransferJob.Status.RUNNING],
        ).first()
        if active:
            return active, 202, None
        raise

    # PostgreSQL remains the source of truth. If Redis is unavailable, the
    # job stays queued and the periodic dispatcher retries publication.
    dispatch_transfer_job(job.pk)
    return job, 202, None


def has_spotify_connection(session_fingerprint):
    """Check whether the current session has a persisted Spotify credential."""
    return OAuthCredential.objects.filter(
        session_fingerprint=session_fingerprint,
        provider=OAuthCredential.Provider.SPOTIFY,
    ).exists()


def get_transfer_job_for_session(*, session_fingerprint, job_id):
    """Return a transfer job only when it belongs to the requesting session."""
    return TransferJob.objects.filter(
        pk=job_id,
        session_fingerprint=session_fingerprint,
    ).first()


def get_transfer_report_for_session(*, session_fingerprint, job_id):
    """Return an owned job and its report, or None when the job is not owned."""
    job = get_transfer_job_for_session(
        session_fingerprint=session_fingerprint,
        job_id=job_id,
    )
    if job is None:
        return None
    result = job.result if isinstance(job.result, dict) else {}
    report = result.get("report", [])
    return job, report if isinstance(report, list) else []
