from datetime import timedelta
from io import StringIO
from unittest.mock import patch

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase
from django.utils import timezone

from config.celery import app as celery_app
from transfer.models import TransferJob
from transfer.services.transfer_dispatch import (
    dispatch_pending_transfers,
    dispatch_transfer_job,
)


class TransferDispatchTests(TestCase):
    def test_celery_beat_schedules_dispatcher_every_minute(self):
        entry = celery_app.conf.beat_schedule["dispatch-queued-transfers-every-minute"]
        self.assertEqual(entry["task"], "transfer.tasks.dispatch_queued_transfers")
        self.assertEqual(entry["schedule"], 60.0)

    def create_job(self, fingerprint, *, status=TransferJob.Status.QUEUED, attempted_at=None):
        return TransferJob.objects.create(
            session_fingerprint=fingerprint,
            source_url="https://vk.com/music/playlist/1_2",
            status=status,
            dispatch_attempted_at=attempted_at,
        )

    @patch("transfer.tasks.run_transfer.delay")
    def test_dispatches_queued_job_and_acquires_lease_once(self, enqueue):
        job = self.create_job("a" * 64)

        self.assertTrue(dispatch_transfer_job(job.pk))
        self.assertFalse(dispatch_transfer_job(job.pk))
        job.refresh_from_db()

        self.assertEqual(job.status, TransferJob.Status.QUEUED)
        self.assertEqual(job.dispatch_attempts, 1)
        self.assertIsNotNone(job.dispatch_attempted_at)
        enqueue.assert_called_once_with(str(job.pk))

    @patch("transfer.tasks.run_transfer.delay")
    def test_retries_only_after_dispatch_cooldown(self, enqueue):
        recent = self.create_job("b" * 64, attempted_at=timezone.now())
        stale = self.create_job(
            "c" * 64,
            attempted_at=timezone.now() - timedelta(minutes=5),
        )

        result = dispatch_pending_transfers(retry_after_seconds=120)

        self.assertEqual(result, {"eligible": 1, "dispatched": 1, "failed": 0})
        recent.refresh_from_db()
        stale.refresh_from_db()
        self.assertEqual(recent.dispatch_attempts, 0)
        self.assertEqual(stale.dispatch_attempts, 2)
        enqueue.assert_called_once_with(str(stale.pk))

    @patch("transfer.tasks.run_transfer.delay", side_effect=RuntimeError("Redis unavailable"))
    def test_broker_failure_keeps_job_queued_and_records_attempt(self, enqueue):
        job = self.create_job("d" * 64)

        result = dispatch_pending_transfers()

        job.refresh_from_db()
        self.assertEqual(result, {"eligible": 1, "dispatched": 0, "failed": 1})
        self.assertEqual(job.status, TransferJob.Status.QUEUED)
        self.assertEqual(job.dispatch_attempts, 1)
        self.assertIsNotNone(job.dispatch_attempted_at)
        enqueue.assert_called_once()

    @patch("transfer.tasks.run_transfer.delay")
    def test_dry_run_does_not_claim_or_publish_jobs(self, enqueue):
        job = self.create_job("e" * 64)

        result = dispatch_pending_transfers(dry_run=True)

        job.refresh_from_db()
        self.assertEqual(result, {"eligible": 1, "dispatched": 0, "failed": 0})
        self.assertEqual(job.dispatch_attempts, 0)
        self.assertIsNone(job.dispatch_attempted_at)
        enqueue.assert_not_called()

    def test_dispatch_command_validates_options(self):
        with self.assertRaises(CommandError):
            call_command("dispatch_queued_transfers", "--batch-size", "0")

    @patch("transfer.tasks.run_transfer.delay")
    def test_dispatch_command_dry_run_reports_eligible_jobs(self, enqueue):
        self.create_job("f" * 64)
        output = StringIO()

        call_command("dispatch_queued_transfers", "--dry-run", stdout=output)

        self.assertIn("1 queued transfer job(s)", output.getvalue())
        enqueue.assert_not_called()
