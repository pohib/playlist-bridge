"""Serialization helpers for API resources."""
from ..models import TransferJob


def serialize_job(job):
    """Serialize a transfer job without exposing session or provider secrets."""
    return {
        "id": str(job.pk),
        "status": job.status,
        "progress": job.progress,
        "total": job.total,
        "matched": job.matched,
        "not_found": job.not_found,
        "ambiguous": job.ambiguous,
        "error": (
            "Перенос не выполнен. Перед повтором проверь целевой плейлист: "
            "часть композиций могла уже добавиться."
            if job.status == TransferJob.Status.FAILED
            else None
        ),
        "created_at": job.created_at.isoformat(),
        "started_at": job.started_at.isoformat() if job.started_at else None,
        "finished_at": job.finished_at.isoformat() if job.finished_at else None,
        "target_playlist_id": (
            job.result.get("target_playlist_id")
            or (job.checkpoint.get("target_playlist_id") if isinstance(job.checkpoint, dict) else None)
        ),
    }
