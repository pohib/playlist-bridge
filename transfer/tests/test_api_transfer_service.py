from unittest.mock import patch

from django.db import IntegrityError
from django.test import TestCase

from transfer.models import TransferJob
from transfer.services.api_transfer_service import create_or_reuse_transfer_job


class CreateOrReuseTransferJobTests(TestCase):
    def setUp(self):
        self.fingerprint = "test-session-fingerprint"

    @patch("transfer.tasks.run_transfer.delay")
    def test_creates_job_and_enqueues_once(self, enqueue):
        job, status, error = create_or_reuse_transfer_job(
            session_fingerprint=self.fingerprint,
            source_url="https://vk.com/music/playlist/1_2",
            target_playlist="A" * 22,
        )
        self.assertEqual(status, 202)
        self.assertIsNone(error)
        self.assertEqual(job.status, TransferJob.Status.QUEUED)
        enqueue.assert_called_once_with(str(job.pk))

    @patch("transfer.tasks.run_transfer.delay")
    def test_reuses_existing_active_job_without_second_enqueue(self, enqueue):
        existing = TransferJob.objects.create(
            session_fingerprint=self.fingerprint,
            source_url="https://vk.com/music/playlist/1_2",
        )
        job, status, error = create_or_reuse_transfer_job(
            session_fingerprint=self.fingerprint,
            source_url="https://vk.com/music/playlist/3_4",
        )
        self.assertEqual(job.pk, existing.pk)
        self.assertEqual(status, 202)
        self.assertIsNone(error)
        enqueue.assert_not_called()

    @patch("transfer.tasks.run_transfer.delay", side_effect=RuntimeError("broker unavailable"))
    def test_queue_failure_marks_job_failed_and_returns_503(self, enqueue):
        job, status, error = create_or_reuse_transfer_job(
            session_fingerprint=self.fingerprint,
            source_url="https://vk.com/music/playlist/1_2",
        )
        job.refresh_from_db()
        self.assertEqual(status, 503)
        self.assertIn("Очередь задач недоступна", error)
        self.assertEqual(job.status, TransferJob.Status.FAILED)
        self.assertIsNotNone(job.finished_at)

    @patch("transfer.services.api_transfer_service.TransferJob.objects.create")
    @patch("transfer.tasks.run_transfer.delay")
    def test_integrity_race_reuses_job_created_by_concurrent_request(self, enqueue, create):
        existing = TransferJob.objects.create(
            session_fingerprint=self.fingerprint,
            source_url="https://vk.com/music/playlist/1_2",
        )
        create.side_effect = IntegrityError("concurrent insert")
        job, status, error = create_or_reuse_transfer_job(
            session_fingerprint=self.fingerprint,
            source_url="https://vk.com/music/playlist/3_4",
        )
        self.assertEqual(job.pk, existing.pk)
        self.assertEqual(status, 202)
        self.assertIsNone(error)
        enqueue.assert_not_called()

    @patch("transfer.services.api_transfer_service.TransferJob.objects.create")
    def test_unrelated_integrity_error_is_not_swallowed(self, create):
        create.side_effect = IntegrityError("unrelated constraint")
        with self.assertRaises(IntegrityError):
            create_or_reuse_transfer_job(
                session_fingerprint=self.fingerprint,
                source_url="https://vk.com/music/playlist/1_2",
            )
