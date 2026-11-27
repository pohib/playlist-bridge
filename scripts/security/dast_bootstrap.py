"""Create isolated users and records for authenticated CI DAST checks."""
import hashlib
import hmac
import os
import uuid

from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.password_validation import validate_password

from transfer.models import TransferJob

password = os.environ["DAST_PASSWORD"]
User = get_user_model()
fixtures = (
    ("zap_dast_user_one", uuid.UUID("10000000-0000-4000-8000-000000000001")),
    ("zap_dast_user_two", uuid.UUID("20000000-0000-4000-8000-000000000002")),
)

for username, job_id in fixtures:
    user, _ = User.objects.get_or_create(
        username=username,
        defaults={"email": f"{username}@example.invalid"},
    )
    user.is_active = True
    validate_password(password, user=user)
    user.set_password(password)
    user.save(update_fields=["password", "is_active"])

    subject = f"user:{user.pk}"
    fingerprint = hmac.new(
        settings.SECRET_KEY.encode(),
        subject.encode(),
        hashlib.sha256,
    ).hexdigest()
    TransferJob.objects.update_or_create(
        pk=job_id,
        defaults={
            "session_fingerprint": fingerprint,
            "source_url": "https://vk.com/playlist-1_1",
            "target_playlist": "",
            "status": TransferJob.Status.FAILED,
            "error": "Isolated CI DAST fixture",
        },
    )

print("DAST fixtures created")
