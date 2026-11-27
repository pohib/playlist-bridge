from django.core.management.base import BaseCommand, CommandError

from transfer.services.transfer_dispatch import dispatch_pending_transfers


class Command(BaseCommand):
    help = "Dispatch queued transfer jobs that have not reached a Celery worker."

    def add_arguments(self, parser):
        parser.add_argument("--retry-after-seconds", type=int, default=120)
        parser.add_argument("--batch-size", type=int, default=100)
        parser.add_argument("--dry-run", action="store_true")

    def handle(self, *args, **options):
        retry_after_seconds = options["retry_after_seconds"]
        batch_size = options["batch_size"]
        if retry_after_seconds < 1:
            raise CommandError("--retry-after-seconds must be greater than zero.")
        if batch_size < 1:
            raise CommandError("--batch-size must be greater than zero.")

        result = dispatch_pending_transfers(
            retry_after_seconds=retry_after_seconds,
            batch_size=batch_size,
            dry_run=options["dry_run"],
        )
        if options["dry_run"]:
            self.stdout.write(
                f"Dry run: {result['eligible']} queued transfer job(s) are eligible for dispatch."
            )
            return

        self.stdout.write(
            self.style.SUCCESS(
                f"Eligible: {result['eligible']}; dispatched: {result['dispatched']}; "
                f"dispatch failures: {result['failed']}."
            )
        )
