from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from transfer.services.security_event_retention import purge_security_events


class Command(BaseCommand):
    help = "Delete expired authentication telemetry containing IP addresses and User-Agent data."

    def add_arguments(self, parser):
        parser.add_argument(
            "--days",
            type=int,
            default=None,
            help="Retention period in days (defaults to SECURITY_EVENT_RETENTION_DAYS).",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Only report how many expired events would be deleted.",
        )

    def handle(self, *args, **options):
        days = options["days"]
        if days is None:
            days = settings.SECURITY_EVENT_RETENTION_DAYS
        if days < 1:
            raise CommandError("--days must be at least one.")

        result = purge_security_events(days=days, dry_run=options["dry_run"])
        if options["dry_run"]:
            self.stdout.write(
                self.style.WARNING(
                    f"Проверка завершена: найдено просроченных событий — {result['matched']}; "
                    f"срок хранения — {result['days']} дн. Удаление не выполнялось."
                )
            )
            return
        self.stdout.write(
            self.style.SUCCESS(
                f"Удалено просроченных событий безопасности: {result['deleted']}; "
                f"срок хранения — {result['days']} дн."
            )
        )
