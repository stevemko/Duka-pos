from datetime import timedelta

from django.conf import settings
from django.core.management.base import BaseCommand
from django.utils import timezone

from sales.models import Payment
from sales.mpesa import MpesaError, query_stk_push


class Command(BaseCommand):
    help = (
        "Ask Daraja for the status of M-Pesa STK payments whose callback never "
        "arrived, and mark them succeeded or failed."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--older-than",
            type=int,
            default=settings.MPESA_STK_PENDING_TIMEOUT_MINUTES,
            help="Only reconcile pending prompts older than this many minutes.",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Print what would change without updating any payment.",
        )

    def handle(self, *args, **options):
        older_than = options["older_than"]
        dry_run = options["dry_run"]
        cutoff = timezone.now() - timedelta(minutes=older_than)
        pending = Payment.objects.select_related("receipt").filter(
            method=Payment.Method.MPESA_STK,
            status=Payment.Status.PENDING,
            created_at__lt=cutoff,
        )

        total = pending.count()
        self.stdout.write(f"Checking {total} pending STK payment(s) older than {older_than} minute(s).")
        if not total:
            return

        succeeded = failed = still_pending = errored = 0
        for payment in pending.iterator():
            if not payment.checkout_request_id:
                self._mark(
                    payment, Payment.Status.FAILED,
                    "Timed out before Safaricom returned a checkout request ID.",
                    dry_run,
                )
                failed += 1
                continue

            try:
                response = query_stk_push(payment)
            except MpesaError as error:
                self.stderr.write(f"{payment.id}: could not query Daraja: {error}")
                errored += 1
                continue

            result_code = str(response.get("ResultCode", response.get("ResponseCode", "")))
            description = str(
                response.get("ResultDesc") or response.get("ResponseDescription") or ""
            )[:255]

            if result_code == "0":
                self._mark(
                    payment, Payment.Status.SUCCEEDED,
                    description or "Confirmed by Daraja status query.",
                    dry_run,
                )
                succeeded += 1
            elif result_code in {"1032", "1037", "9999"}:
                # Customer never responded / prompt timed out: safe to fail and retry.
                self._mark(
                    payment, Payment.Status.FAILED,
                    description or "Customer did not complete the M-Pesa prompt.",
                    dry_run,
                )
                failed += 1
            else:
                self.stdout.write(
                    f"{payment.id}: still pending (Daraja code {result_code or 'unknown'})."
                )
                still_pending += 1

        prefix = "Would mark" if dry_run else "Marked"
        self.stdout.write(self.style.SUCCESS(
            f"{prefix} {succeeded} succeeded, {failed} failed; "
            f"{still_pending} still pending, {errored} could not be queried."
        ))

    @staticmethod
    def _mark(payment, status, description, dry_run):
        if dry_run:
            return
        payment.status = status
        payment.result_description = description
        payment.save(update_fields=["status", "result_description"])
