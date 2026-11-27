"""Account workspace ownership transfer from an anonymous session to a user."""

from django.db import transaction

from ..models import LibraryProfile, OAuthCredential, TransferJob


def attach_anonymous_workspace(*, user, previous_fingerprint, current_fingerprint):
    """Move anonymous library data and credentials into the authenticated session."""
    if previous_fingerprint == current_fingerprint:
        return

    with transaction.atomic():
        anonymous_profile = LibraryProfile.objects.filter(
            session_fingerprint=previous_fingerprint,
            user__isnull=True,
        ).first()
        account_profile = LibraryProfile.objects.filter(user=user).first()

        if anonymous_profile:
            if account_profile:
                anonymous_profile.playlists.update(profile=account_profile)
                anonymous_profile.transfers.update(profile=account_profile)
                anonymous_profile.delete()
            else:
                anonymous_profile.user = user
                anonymous_profile.session_fingerprint = current_fingerprint
                anonymous_profile.save(update_fields=["user", "session_fingerprint", "updated_at"])

        for credential in OAuthCredential.objects.filter(session_fingerprint=previous_fingerprint):
            duplicate = OAuthCredential.objects.filter(
                session_fingerprint=current_fingerprint,
                provider=credential.provider,
            ).exclude(pk=credential.pk).exists()
            if duplicate:
                credential.delete()
            else:
                credential.session_fingerprint = current_fingerprint
                credential.save(update_fields=["session_fingerprint", "updated_at"])

        # Preserve finished reports; avoid violating the one-active-job-per-owner constraint.
        active_exists = TransferJob.objects.filter(
            session_fingerprint=current_fingerprint,
            status__in=(TransferJob.Status.QUEUED, TransferJob.Status.RUNNING),
        ).exists()
        old_jobs = TransferJob.objects.filter(session_fingerprint=previous_fingerprint)
        if active_exists:
            old_jobs.exclude(status__in=(TransferJob.Status.QUEUED, TransferJob.Status.RUNNING)).update(
                session_fingerprint=current_fingerprint
            )
        else:
            old_jobs.update(session_fingerprint=current_fingerprint)
