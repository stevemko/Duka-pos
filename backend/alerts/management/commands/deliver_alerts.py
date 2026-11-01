from datetime import timedelta

from django.core.management.base import BaseCommand
from django.utils import timezone

from alerts.models import StockAlert
from alerts.whatsapp import send_restock_whatsapp


class Command(BaseCommand):
    help = (
        "Send the restock WhatsApp alerts that a sale queued, and mark them sent. "
        "Runs on a schedule so the checkout never waits on Twilio."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--max-age-hours",
            type=int,
            default=24,
            help="Skip alerts older than this; last week's low stock is not news any more.",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Report what would be sent without messaging anyone.",
        )

    def handle(self, *args, **options):
        cutoff = timezone.now() - timedelta(hours=options["max_age_hours"])
        pending = (
            StockAlert.objects.select_related("product")
            .filter(whatsapp_sent=False)
            .order_by("triggered_at")
        )
        current = pending.filter(triggered_at__gte=cutoff)
        # Counted before anything is marked, because each send takes a row out of
        # the very queryset these numbers describe.
        expired = pending.exclude(triggered_at__gte=cutoff).count()
        sent = skipped = 0
        messaged_products = set()

        for alert in current.iterator():
            # The alert says what the shelf holds now, so a product restocked in
            # the meantime must not announce a shortage that no longer exists.
            if not alert.product.needs_restock:
                if not options["dry_run"]:
                    alert.whatsapp_sent = True
                    alert.save(update_fields=["whatsapp_sent"])
                skipped += 1
                continue

            # One shortage is one message, even if it was crossed several times.
            if alert.product_id in messaged_products:
                if not options["dry_run"]:
                    alert.whatsapp_sent = True
                    alert.save(update_fields=["whatsapp_sent"])
                skipped += 1
                continue

            if options["dry_run"]:
                self.stdout.write(f"Would send a restock alert for {alert.product.name}.")
                sent += 1
                continue

            if send_restock_whatsapp(alert.product):
                alert.whatsapp_sent = True
                alert.save(update_fields=["whatsapp_sent"])
                messaged_products.add(alert.product_id)
                sent += 1
            else:
                # Either Twilio is not configured or it refused; the row stays
                # queued so the next run tries again.
                self.stderr.write(f"{alert.id}: {alert.product.name} could not be sent; will retry.")

        summary = f"Sent {sent}, closed {skipped} no-longer-relevant alert(s)."
        if expired > 0:
            summary += (
                f" {expired} alert(s) older than {options['max_age_hours']} hour(s) were left alone."
            )
        self.stdout.write(self.style.SUCCESS(summary))
