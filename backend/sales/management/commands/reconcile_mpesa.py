from datetime import timedelta

from django.conf import settings
from django.core.management.base import BaseCommand
from django.utils import timezone

from sales.models import Payment
from sales.mpesa import MpesaError, apply_query_result, query_stk_push


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
                    "Timed out before Safaricom returned a checkout request ID.", "",
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

            new_status, description, reference = apply_query_result(payment, response)
            if new_status is None:
                self.stdout.write(
                    f"{payment.id}: still pending ({description or 'no description from Daraja'})."
                )
                still_pending += 1
                continue

            self._mark(payment, new_status, description, reference, dry_run)
            if new_status == Payment.Status.SUCCEEDED:
                succeeded += 1
            else:
                failed += 1

        prefix = "Would mark" if dry_run else "Marked"
        self.stdout.write(self.style.SUCCESS(
            f"{prefix} {succeeded} succeeded, {failed} failed; "
            f"{still_pending} still pending, {errored} could not be queried."
        ))

    @staticmethod
    def _mark(payment, status, description, reference, dry_run):
        if dry_run:
            return
        payment.status = status
        payment.result_description = description
        # The prompt may already carry the code from a partial callback; never
        # overwrite a recorded M-Pesa receipt code with a blank.
        fields = ["status", "result_description"]
        if reference:
            payment.reference = reference
            fields.append("reference")
        payment.save(update_fields=fields)
