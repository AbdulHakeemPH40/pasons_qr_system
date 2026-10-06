"""Close visits whose expiry has passed. Safe to run from cron."""

from django.core.management.base import BaseCommand
from django.utils import timezone

from apps.kidsplay.models import TableVisit
from apps.kidsplay.services import rewards


class Command(BaseCommand):
    help = "Close expired table visits and expire overdue redemptions."

    def handle(self, *args, **options):
        now = timezone.now()
        visits = TableVisit.objects.filter(closed_at__isnull=True, expires_at__lte=now)
        count = visits.update(closed_at=now)
        redemptions = rewards.expire_due()
        self.stdout.write(f"closed {count} visits, refunded {redemptions} redemptions")
