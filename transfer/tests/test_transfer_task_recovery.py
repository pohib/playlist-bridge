from datetime import timedelta
from io import StringIO
from unittest.mock import patch

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase
from django.utils import timezone

from transfer.api.serializers import serialize_job
from transfer.models import TransferJob
from transfer.tasks import run_transfer


class FailStaleTransfersCommandTests(TestCase):
    def create_job(self, *, status, fingerprint, started_at, heartbeat_at=None, checkpoint=None):
        return TransferJob.objects.create(
            session_fingerprint=fingerprint,
            source_url="https://vk.com/music/playlist/1_2",
            status=status,
            started_at=started_at,
            heartbeat_at=heartbeat_at,
            checkpoint=checkpoint or {},
        )

    @patch("transfer.management.commands.fail_stale_transfers.dispatch_transfer_job", return_value=True)
    def test_resumes_stale_jobs_only_when_safe_checkpoint_exists(self, dispatch):
        now = timezone.now()
        recoverable = self.create_job(
            status=TransferJob.Status.RUNNING,
            fingerprint="a" * 64,
            started_at=now - timedelta(hours=2),
            heartbeat_at=now - timedelta(hours=2),
            checkpoint={
                "report": [{"index": 1, "status": "matched"}],
                "matched_uris": ["spotify:track:" + "A" * 22],
                "playlist_create_pending": False,
            },
        )
        unsafe = self.create_job(
            status=TransferJob.Status.RUNNING,
            fingerprint="b" * 64,
            started_at=now - timedelta(hours=2),
            heartbeat_at=now - timedelta(hours=2),
            checkpoint={
                "report": [{"index": 1, "status": "matched"}],
                "matched_uris": ["spotify:track:" + "A" * 22],
                "playlist_create_pending": True,
            },
        )
        legacy_stale = self.create_job(
            status=TransferJob.Status.RUNNING,
            fingerprint="c" * 64,
            started_at=now - timedelta(hours=2),
        )
        fresh = self.create_job(
            status=TransferJob.Status.RUNNING,
            fingerprint="d" * 64,
            started_at=now - timedelta(minutes=10),
            heartbeat_at=now - timedelta(minutes=10),
        )
        queued = self.create_job(
            status=TransferJob.Status.QUEUED,
            fingerprint="e" * 64,
            started_at=now - timedelta(hours=2),
        )

        output = StringIO()
        call_command(
            "fail_stale_transfers",
            "--older-than-minutes",
            "60",
            stdout=output,
        )

        recoverable.refresh_from_db()
        unsafe.refresh_from_db()
        legacy_stale.refresh_from_db()
        fresh.refresh_from_db()
        queued.refresh_from_db()

        self.assertEqual(recoverable.status, TransferJob.Status.QUEUED)
        self.assertEqual(recoverable.error, "")
        self.assertIsNone(recoverable.finished_at)
        self.assertEqual(unsafe.status, TransferJob.Status.FAILED)
        self.assertIn("проверь целевой плейлист Spotify", unsafe.error)
        self.assertEqual(legacy_stale.status, TransferJob.Status.FAILED)
        self.assertEqual(fresh.status, TransferJob.Status.RUNNING)
        self.assertEqual(queued.status, TransferJob.Status.QUEUED)
        dispatch.assert_called_once_with(recoverable.pk, retry_after_seconds=1)
        self.assertIn("Resumed 1 stale transfer job(s)", output.getvalue())

    def test_dry_run_does_not_change_job_state(self):
        now = timezone.now()
        job = self.create_job(
            status=TransferJob.Status.RUNNING,
            fingerprint="f" * 64,
            started_at=now - timedelta(hours=2),
            heartbeat_at=now - timedelta(hours=2),
        )

        output = StringIO()
        call_command(
            "fail_stale_transfers",
            "--older-than-minutes",
            "60",
            "--dry-run",
            stdout=output,
        )

        job.refresh_from_db()
        self.assertEqual(job.status, TransferJob.Status.RUNNING)
        self.assertIsNone(job.finished_at)
        self.assertIn(
            "0 stale job(s) are resumable; 1 job(s) would be marked failed",
            output.getvalue(),
        )

    def test_rejects_non_positive_stale_threshold(self):
        with self.assertRaises(CommandError):
            call_command("fail_stale_transfers", "--older-than-minutes", "0")


class RunTransferTaskHeartbeatTests(TestCase):
    @staticmethod
    def result_payload():
        return {
            "total": 2,
            "matched": 1,
            "not_found": 1,
            "ambiguous": 0,
            "report": [],
            "target_playlist_id": "A" * 22,
        }

    def setUp(self):
        self.job = TransferJob.objects.create(
            session_fingerprint="g" * 64,
            source_url="https://vk.com/music/playlist/1_2",
        )

    @patch("transfer.tasks.SpotifyClient")
    @patch("transfer.tasks.get_access_token", return_value=("access-token", {}))
    @patch("transfer.tasks.execute_transfer")
    def test_task_updates_heartbeat_and_finishes_successfully(
        self,
        execute_transfer,
        get_access_token,
        spotify_factory,
    ):
        def execute(**kwargs):
            kwargs["progress_callback"]({
                "progress": 50,
                "total": 2,
                "matched": 1,
                "not_found": 1,
                "ambiguous": 0,
            })
            kwargs["checkpoint_callback"]({"target_playlist_id": "A" * 22})
            return self.result_payload()

        execute_transfer.side_effect = execute
        run_transfer.run(str(self.job.pk))

        self.job.refresh_from_db()
        self.assertEqual(self.job.status, TransferJob.Status.SUCCEEDED)
        self.assertEqual(self.job.progress, 100)
        self.assertEqual(self.job.matched, 1)
        self.assertEqual(self.job.checkpoint["target_playlist_id"], "A" * 22)
        self.assertIsNotNone(self.job.started_at)
        self.assertIsNotNone(self.job.heartbeat_at)
        self.assertGreaterEqual(self.job.heartbeat_at, self.job.started_at)
        execute_transfer.assert_called_once()
        get_access_token.assert_called_once()
        spotify_factory.assert_called_once()

    @patch("transfer.tasks.SpotifyClient")
    @patch("transfer.tasks.get_access_token", return_value=("access-token", {}))
    @patch("transfer.tasks.execute_transfer")
    def test_duplicate_delivery_does_not_execute_completed_job_again(
        self,
        execute_transfer,
        get_access_token,
        spotify_factory,
    ):
        execute_transfer.return_value = self.result_payload()
        run_transfer.run(str(self.job.pk))
        run_transfer.run(str(self.job.pk))

        self.job.refresh_from_db()
        self.assertEqual(self.job.status, TransferJob.Status.SUCCEEDED)
        execute_transfer.assert_called_once()
        get_access_token.assert_called_once()
        spotify_factory.assert_called_once()

    @patch("transfer.tasks.SpotifyClient")
    @patch("transfer.tasks.get_access_token", return_value=("access-token", {}))
    @patch("transfer.tasks.execute_transfer")
    def test_task_does_not_overwrite_state_changed_during_provider_call(
        self,
        execute_transfer,
        get_access_token,
        spotify_factory,
    ):
        def execute(**kwargs):
            TransferJob.objects.filter(pk=self.job.pk).update(
                status=TransferJob.Status.FAILED,
                error="marked stale by recovery command",
            )
            return self.result_payload()

        execute_transfer.side_effect = execute
        run_transfer.run(str(self.job.pk))

        self.job.refresh_from_db()
        self.assertEqual(self.job.status, TransferJob.Status.FAILED)
        self.assertEqual(self.job.error, "marked stale by recovery command")
        execute_transfer.assert_called_once()
        get_access_token.assert_called_once()
        spotify_factory.assert_called_once()


class TransferJobSerializerSafetyTests(TestCase):
    def test_failed_job_does_not_expose_saved_target_playlist_id(self):
        job = TransferJob.objects.create(
            session_fingerprint="h" * 64,
            source_url="https://vk.com/music/playlist/1_2",
            status=TransferJob.Status.FAILED,
            error="worker interrupted",
            checkpoint={"target_playlist_id": "A" * 22},
        )

        payload = serialize_job(job)

        self.assertIn("проверь целевой плейлист", payload["error"])
        self.assertIsNone(payload["target_playlist_id"])
        self.assertEqual(job.checkpoint["target_playlist_id"], "A" * 22)
