from unittest.mock import patch

from django.db import IntegrityError
from django.test import TestCase

from transfer.models import OAuthCredential, TransferJob
from transfer.services.api_transfer_service import (
    create_or_reuse_transfer_job,
    get_transfer_job_for_session,
    get_transfer_report_for_session,
    has_spotify_connection,
)


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
    def test_queue_failure_keeps_job_queued_for_periodic_dispatch(self, enqueue):
        job, status, error = create_or_reuse_transfer_job(
            session_fingerprint=self.fingerprint,
            source_url="https://vk.com/music/playlist/1_2",
        )
        job.refresh_from_db()
        self.assertEqual(status, 202)
        self.assertIsNone(error)
        self.assertEqual(job.status, TransferJob.Status.QUEUED)
        self.assertEqual(job.dispatch_attempts, 1)
        self.assertIsNotNone(job.dispatch_attempted_at)
        self.assertIsNone(job.finished_at)

    @patch("transfer.services.api_transfer_service.TransferJob.objects.filter")
    @patch("transfer.services.api_transfer_service.TransferJob.objects.create")
    @patch("transfer.tasks.run_transfer.delay")
    def test_integrity_race_reuses_job_created_by_concurrent_request(
        self, enqueue, create, filter_jobs
    ):
        # The competing transaction commits its row after our first lookup.
        # Mock the two reads to model that visibility without sharing a DB
        # transaction (which would roll the competing insert back as well).
        existing = TransferJob(
            id="b8c6f2f4-1f91-4f2a-8b6a-6c45c2e1f5a0",
            session_fingerprint=self.fingerprint,
            source_url="https://vk.com/music/playlist/1_2",
        )
        filter_jobs.return_value.first.side_effect = [None, existing]
        create.side_effect = IntegrityError("concurrent insert")

        job, status, error = create_or_reuse_transfer_job(
            session_fingerprint=self.fingerprint,
            source_url="https://vk.com/music/playlist/3_4",
        )

        self.assertEqual(job.pk, existing.pk)
        self.assertEqual(status, 202)
        self.assertIsNone(error)
        self.assertEqual(filter_jobs.return_value.first.call_count, 2)
        enqueue.assert_not_called()

    @patch("transfer.services.api_transfer_service.TransferJob.objects.create")
    def test_unrelated_integrity_error_is_not_swallowed(self, create):
        create.side_effect = IntegrityError("unrelated constraint")
        with self.assertRaises(IntegrityError):
            create_or_reuse_transfer_job(
                session_fingerprint=self.fingerprint,
                source_url="https://vk.com/music/playlist/1_2",
            )



class TransferApiOwnershipServiceTests(TestCase):
    def setUp(self):
        self.fingerprint = "owned-session-fingerprint"
        self.other_fingerprint = "another-session-fingerprint"

    def test_spotify_connection_check_is_scoped_to_session(self):
        self.assertFalse(has_spotify_connection(self.fingerprint))
        OAuthCredential.objects.create(
            session_fingerprint=self.fingerprint,
            provider=OAuthCredential.Provider.SPOTIFY,
            encrypted_payload="encrypted-token-payload",
        )
        self.assertTrue(has_spotify_connection(self.fingerprint))
        self.assertFalse(has_spotify_connection(self.other_fingerprint))

    def test_transfer_job_lookup_does_not_cross_session_boundary(self):
        job = TransferJob.objects.create(
            session_fingerprint=self.fingerprint,
            source_url="https://vk.com/music/playlist/1_2",
        )
        self.assertEqual(
            get_transfer_job_for_session(
                session_fingerprint=self.fingerprint,
                job_id=job.pk,
            ),
            job,
        )
        self.assertIsNone(
            get_transfer_job_for_session(
                session_fingerprint=self.other_fingerprint,
                job_id=job.pk,
            )
        )

    def test_report_lookup_returns_only_owned_succeeded_report(self):
        job = TransferJob.objects.create(
            session_fingerprint=self.fingerprint,
            source_url="https://vk.com/music/playlist/1_2",
            status=TransferJob.Status.SUCCEEDED,
            result={"report": [{"status": "matched"}]},
        )
        self.assertEqual(
            get_transfer_report_for_session(
                session_fingerprint=self.fingerprint,
                job_id=job.pk,
            ),
            (job, [{"status": "matched"}]),
        )
        self.assertIsNone(
            get_transfer_report_for_session(
                session_fingerprint=self.other_fingerprint,
                job_id=job.pk,
            )
        )

    def test_report_lookup_normalizes_malformed_stored_report(self):
        job = TransferJob.objects.create(
            session_fingerprint=self.fingerprint,
            source_url="https://vk.com/music/playlist/1_2",
            status=TransferJob.Status.SUCCEEDED,
            result={"report": "unexpected"},
        )
        self.assertEqual(
            get_transfer_report_for_session(
                session_fingerprint=self.fingerprint,
                job_id=job.pk,
            ),
            (job, []),
        )
