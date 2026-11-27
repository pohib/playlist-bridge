from django.core.management.base import BaseCommand, CommandError

from transfer.services.transfer_dispatch import recover_stale_transfers


class Command(BaseCommand):
    help = "Safely recover stale transfers with persisted Spotify checkpoints."

    def add_arguments(self, parser):
        parser.add_argument(
            "--older-than-minutes",
            type=int,
            default=60,
            help="Minimum heartbeat age before a running job is considered stale (default: 60).",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Only report which stale jobs can be resumed safely.",
        )

    def handle(self, *args, **options):
        older_than_minutes = options["older_than_minutes"]
        if older_than_minutes < 1:
            raise CommandError("--older-than-minutes must be greater than zero.")

        result = recover_stale_transfers(
            older_than_minutes=older_than_minutes,
            dry_run=options["dry_run"],
        )
        if options["dry_run"]:
            self.stdout.write(
                self.style.WARNING(
                    f"Dry run: {result['resumable']} stale job(s) are resumable; "
                    f"{result['failed']} job(s) would be marked failed."
                )
            )
            return result

        self.stdout.write(
            self.style.SUCCESS(
                f"Resumed {result['resumed']} stale transfer job(s); "
                f"dispatched {result['dispatched']}; "
                f"dispatch failures {result['dispatch_failed']}; "
                f"marked failed {result['failed']}."
            )
        )
        return result
