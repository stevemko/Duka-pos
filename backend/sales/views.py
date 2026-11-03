import csv
import hashlib
import hmac
import json
import logging
from datetime import date, timedelta
from decimal import Decimal, InvalidOperation, ROUND_DOWN, ROUND_HALF_UP

from django.db import IntegrityError, transaction
from django.db.models import F, Q, Sum
from django.db.models.functions import TruncDate, TruncWeek
from django.http import HttpResponse
from django.utils import timezone
from django.utils.dateparse import parse_date
from decouple import config
from rest_framework import serializers, status, viewsets
from rest_framework.decorators import (
    action,
    api_view,
    authentication_classes,
    permission_classes,
    throttle_classes,
)
from rest_framework.exceptions import APIException, PermissionDenied, ValidationError
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response

from accounts.models import Branch
from accounts.permissions import IsManager, IsSuperUser
from accounts.services import (
    branch_queryset,
    main_branch,
    payments_branch_queryset,
    sales_branch_queryset,
    sees_all_branches,
    user_branch,
)
from alerts.models import StockAlert
from config.throttles import CheckoutThrottle, PaymentThrottle, StkPushThrottle
from expenses.models import Expense
from products.models import Product
from products.services import move_stock

from .credit import check_credit_limit, find_customer
from .models import (
    Payment,
    Sale,
    SaleReceipt,
    SaleReturn,
    SaleReturnItem,
    unresolved_stk_prompts,
)
from .mpesa import (
    MpesaError,
    MpesaUnconfirmed,
    apply_query_result,
    initiate_stk_push,
    normalize_phone,
    query_stk_push,
)
from .serializers import (
    CheckoutSerializer,
    ReceiptPaymentSerializer,
    ReturnCreateSerializer,
    SaleReceiptSerializer,
    SaleSerializer,
    StkPushSerializer,
)

logger = logging.getLogger(__name__)


def _share(amount, total):
    if not total:
        return Decimal("0.0")
    return (Decimal(amount or 0) / Decimal(total) * 100).quantize(Decimal("0.1"))


def _receipt_queryset():
    return SaleReceipt.objects.select_related("branch", "created_by", "customer").prefetch_related(
        "items__product", "payments__created_by", "returns__items__product"
    ).with_totals()


def _branch_scope(user, requested):
    """Resolve the branch a user may see. None means all branches."""
    if not user.is_staff:
        return user_branch(user) or main_branch()
    if requested and requested != "all":
        branch = Branch.objects.filter(pk=requested).first()
        if branch is None:
            raise ValidationError({"branch": "Unknown branch."})
        if not sees_all_branches(user) and branch != user_branch(user):
            raise ValidationError({"branch": "You can only view your own branch."})
        return branch
    if requested == "all":
        if not sees_all_branches(user):
            raise ValidationError({"branch": "You can only view your own branch."})
        return None
    if sees_all_branches(user):
        return None
    return user_branch(user)


def _assert_receipt_access(user, receipt):
    if sees_all_branches(user):
        return
    allowed = user_branch(user) or main_branch()
    receipt_branch = receipt.branch or main_branch()
    if allowed and receipt_branch and allowed.pk != receipt_branch.pk:
        raise PermissionDenied("This receipt belongs to another branch.")



def _queue_restock_alert(product):
    if not product.needs_restock:
        return None
    already_alerted_today = StockAlert.objects.filter(
        product=product,
        triggered_at__date=timezone.localdate(),
    ).exists()
    if already_alerted_today:
        return None
    alert = StockAlert.objects.create(
        product=product,
        stock_at_trigger=product.stock_quantity,
    )
    return alert.id


class IdempotencyConflict(APIException):
    """The same sale reference arrived with a different basket behind it."""

    status_code = status.HTTP_409_CONFLICT
    default_detail = (
        "That sale reference was already used for a different basket. "
        "Check the basket, then send it again as a new sale."
    )
    default_code = "idempotency_conflict"


def _request_fingerprint(payload):
    """Digest what the till asked to sell, with the keys in a stable order."""
    body = json.dumps(payload, sort_keys=True, default=str)
    return hashlib.sha256(body.encode("utf-8")).hexdigest()


def _replay_or_conflict(receipt, fingerprint):
    """Answer a repeated Idempotency-Key with the receipt it already produced.

    The same key carrying a different basket is not a retry: it is a new sale sent
    with an old reference, and quietly handing back the earlier receipt would give
    this customer someone else's goods and someone else's total.
    """
    if receipt.idempotency_hash and receipt.idempotency_hash != fingerprint:
        raise IdempotencyConflict()
    return Response(SaleReceiptSerializer(receipt).data, status=status.HTTP_200_OK)


def _period_range(params):
    """Resolve a named reporting period using the server's clock, not the till's.

    A laptop left on UTC would otherwise show yesterday's trade as today's: the
    records are stamped in the shop's timezone, so only the shop's clock can say
    which day a receipt belongs to.
    """
    period = (params.get("period") or "").strip()
    if not period or period == "all":
        return None, None
    today = timezone.localdate()
    if period == "today":
        return today, today
    if period == "yesterday":
        day = today - timedelta(days=1)
        return day, day
    if period == "last7":
        return today - timedelta(days=6), today
    if period == "month":
        return today.replace(day=1), today
    raise ValidationError({"period": "Use today, yesterday, last7, month or all."})


class SaleViewSet(viewsets.ModelViewSet):
    queryset = Sale.objects.select_related("product").all()
    serializer_class = SaleSerializer
    http_method_names = ["get", "post", "head", "options"]

    def get_queryset(self):
        queryset = super().get_queryset()
        start_date = self.request.query_params.get("start_date")
        end_date = self.request.query_params.get("end_date")
        product_id = self.request.query_params.get("product")
        branch = _branch_scope(self.request.user, self.request.query_params.get("branch"))
        queryset = sales_branch_queryset(queryset, branch)

        if start_date:
            parsed_start = parse_date(start_date)
            if not parsed_start:
                raise ValidationError({"start_date": "Use YYYY-MM-DD format."})
            queryset = queryset.filter(created_at__date__gte=parsed_start)
        if end_date:
            parsed_end = parse_date(end_date)
            if not parsed_end:
                raise ValidationError({"end_date": "Use YYYY-MM-DD format."})
            queryset = queryset.filter(created_at__date__lte=parsed_end)
        if start_date and end_date and parsed_start > parsed_end:
            raise ValidationError({"end_date": "End date must be on or after start date."})
        if product_id:
            queryset = queryset.filter(product_id=product_id)
        return queryset

    @action(detail=False, methods=["get"], url_path="summary")
    def summary(self, request):
        today = timezone.localdate()
        branch = _branch_scope(request.user, request.query_params.get("branch"))
        sales = sales_branch_queryset(
            Sale.objects.filter(created_at__date=today), branch
        )
        totals = sales.aggregate(
            total_sales=Sum("total"),
            gross_profit=Sum("profit"),
            items_sold=Sum("quantity"),
        )
        # What left the shelf today is not necessarily what was kept: goods handed
        # straight back, and the cash refunded for them, belong in the same day's
        # figures or the takings will not add up at close.
        returns_today = branch_queryset(
            SaleReturn.objects.filter(created_at__date=today), branch
        )
        value_back = returns_today.aggregate(total=Sum("value"))["total"] or Decimal("0.00")
        refund_back = returns_today.aggregate(total=Sum("refund"))["total"] or Decimal("0.00")
        items_back = SaleReturnItem.objects.filter(sale_return__in=returns_today).aggregate(
            quantity=Sum("quantity"), profit=Sum("profit")
        )
        return Response({
            "date": today,
            "total_sales": (totals["total_sales"] or 0) - value_back,
            "gross_profit": (totals["gross_profit"] or 0) - (items_back["profit"] or 0),
            "items_sold": (totals["items_sold"] or 0) - (items_back["quantity"] or 0),
            "returned_value": value_back,
            "amount_refunded": refund_back,
        })

    @action(detail=False, methods=["get"], url_path="analytics")
    def analytics(self, request):
        month_value = request.query_params.get("month", timezone.localdate().strftime("%Y-%m"))
        try:
            month_start = date.fromisoformat(f"{month_value}-01")
        except ValueError as error:
            raise ValidationError({"month": "Use YYYY-MM format."}) from error
        if len(month_value) != 7:
            raise ValidationError({"month": "Use YYYY-MM format."})
        if month_start.month == 12:
            next_month = date(month_start.year + 1, 1, 1)
        else:
            next_month = date(month_start.year, month_start.month + 1, 1)
        today = timezone.localdate()
        branch = _branch_scope(request.user, request.query_params.get("branch"))
        is_manager = bool(request.user.is_staff)
        monthly_sales = sales_branch_queryset(
            Sale.objects.filter(
                created_at__date__gte=month_start,
                created_at__date__lt=next_month,
            ),
            branch,
        )
        totals = monthly_sales.aggregate(
            total_sales=Sum("total"),
            items_sold=Sum("quantity"),
        )
        daily_aggregates = {"total_sales": Sum("total"), "items_sold": Sum("quantity")}
        sold_aggregates = {"quantity_sold": Sum("quantity"), "sales_total": Sum("total")}
        if is_manager:
            totals["gross_profit"] = monthly_sales.aggregate(gross_profit=Sum("profit"))["gross_profit"]
            daily_aggregates["gross_profit"] = Sum("profit")
            sold_aggregates["gross_profit"] = Sum("profit")

        daily_rows = (
            monthly_sales.annotate(day=TruncDate("created_at"))
            .values("day")
            .annotate(**daily_aggregates)
        )
        monthly_payments = payments_branch_queryset(
            Payment.objects.filter(
                status=Payment.Status.SUCCEEDED,
                created_at__date__gte=month_start,
                created_at__date__lt=next_month,
            ),
            branch,
        )
        daily_collections = (
            monthly_payments.annotate(day=TruncDate("created_at"))
            .values("day")
            .annotate(amount_collected=Sum("amount"))
        )
        if is_manager:
            monthly_expenses = branch_queryset(
                Expense.objects.filter(date__gte=month_start, date__lt=next_month), branch
            )
        else:
            monthly_expenses = Expense.objects.none()
        expense_totals = monthly_expenses.aggregate(total_expenses=Sum("amount"))
        daily_expense_rows = monthly_expenses.values("date").annotate(amount_spent=Sum("amount"))

        # What came back this month, counted on the day it was taken back. A refund
        # paid today belongs in today's takings even when the goods sold last month,
        # because that is the day the cash left the till.
        monthly_returns = branch_queryset(
            SaleReturn.objects.filter(
                created_at__date__gte=month_start, created_at__date__lt=next_month
            ),
            branch,
        )
        monthly_return_items = SaleReturnItem.objects.filter(sale_return__in=monthly_returns)
        returned_value = monthly_returns.aggregate(total=Sum("value"))["total"] or Decimal("0.00")
        refunded_total = monthly_returns.aggregate(total=Sum("refund"))["total"] or Decimal("0.00")
        items_back = monthly_return_items.aggregate(
            quantity=Sum("quantity"), profit=Sum("profit")
        )
        returned_quantity = items_back["quantity"] or 0
        returned_profit = items_back["profit"] or Decimal("0.00")

        daily_returned = {}
        for row in (
            monthly_returns.annotate(day=TruncDate("created_at"))
            .values("day")
            .annotate(value_back=Sum("value"), refund_back=Sum("refund"))
        ):
            daily_returned[row["day"].isoformat()] = {
                "value": row["value_back"] or Decimal("0.00"),
                "refund": row["refund_back"] or Decimal("0.00"),
                "quantity": 0,
                "profit": Decimal("0.00"),
            }
        for row in (
            monthly_return_items.annotate(day=TruncDate("sale_return__created_at"))
            .values("day")
            .annotate(quantity_back=Sum("quantity"), profit_back=Sum("profit"))
        ):
            slot = daily_returned.setdefault(
                row["day"].isoformat(),
                {"value": Decimal("0.00"), "refund": Decimal("0.00"),
                 "quantity": 0, "profit": Decimal("0.00")},
            )
            slot["quantity"] = row["quantity_back"] or 0
            slot["profit"] = row["profit_back"] or Decimal("0.00")

        per_product_back = {
            row["product_id"]: row
            for row in monthly_return_items.values("product_id").annotate(
                quantity_back=Sum("quantity"),
                value_back=Sum("total"),
                profit_back=Sum("profit"),
            )
        }
        per_category_back = {
            row["product__category"]: row
            for row in monthly_return_items.values("product__category").annotate(
                value_back=Sum("total"), quantity_back=Sum("quantity")
            )
        }

        def empty_day(day):
            return {
                "date": day,
                "total_sales": Decimal("0.00"),
                "gross_profit": Decimal("0.00"),
                "items_sold": 0,
                "amount_collected": Decimal("0.00"),
                "amount_spent": Decimal("0.00"),
                "amount_returned": Decimal("0.00"),
            }

        daily = {}
        for row in daily_rows:
            day = row["day"].isoformat()
            daily[day] = {
                "date": day,
                "total_sales": row["total_sales"] or Decimal("0.00"),
                "gross_profit": row.get("gross_profit") or Decimal("0.00"),
                "items_sold": row["items_sold"] or 0,
                "amount_collected": Decimal("0.00"),
                "amount_spent": Decimal("0.00"),
                "amount_returned": Decimal("0.00"),
            }
        for row in daily_collections:
            day = row["day"].isoformat()
            daily.setdefault(day, empty_day(day))["amount_collected"] = (
                row["amount_collected"] or Decimal("0.00")
            )
        for row in daily_expense_rows:
            day = row["date"].isoformat()
            daily.setdefault(day, empty_day(day))["amount_spent"] = (
                row["amount_spent"] or Decimal("0.00")
            )
        for day, back in daily_returned.items():
            entry = daily.setdefault(day, empty_day(day))
            entry["total_sales"] -= back["value"]
            entry["items_sold"] -= back["quantity"]
            entry["gross_profit"] -= back["profit"]
            entry["amount_collected"] -= back["refund"]
            entry["amount_returned"] = back["refund"]

        product_performance = [
            {
                "product_id": row["product_id"],
                "product_name": row["product__name"],
                "quantity_sold": (row["quantity_sold"] or 0) - (
                    per_product_back.get(row["product_id"], {}).get("quantity_back") or 0
                ),
                "sales_total": (row["sales_total"] or Decimal("0.00")) - (
                    per_product_back.get(row["product_id"], {}).get("value_back") or Decimal("0.00")
                ),
                "gross_profit": (row.get("gross_profit") or Decimal("0.00")) - (
                    per_product_back.get(row["product_id"], {}).get("profit_back") or Decimal("0.00")
                ),
            }
            for row in monthly_sales.values("product_id", "product__name")
            .annotate(**sold_aggregates)
            .order_by("-quantity_sold", "product__name")
        ]
        sold_ids = [row["product_id"] for row in product_performance]
        products_in_scope = branch_queryset(
            Product.objects.filter(created_at__date__lt=next_month), branch
        )
        stagnant_query = products_in_scope.exclude(id__in=sold_ids)
        stagnant_count = stagnant_query.count()
        stagnant_products = list(stagnant_query.values("id", "name").order_by("name")[:8])

        category_rows = list(
            monthly_sales.values("product__category")
            .annotate(sales_total=Sum("total"), quantity_sold=Sum("quantity"))
            .order_by("-sales_total")
        )
        for row in category_rows:
            back = per_category_back.get(row["product__category"], {})
            row["sales_total"] = (row["sales_total"] or Decimal("0.00")) - (
                back.get("value_back") or Decimal("0.00")
            )
            row["quantity_sold"] = (row["quantity_sold"] or 0) - (
                back.get("quantity_back") or 0
            )
        category_total = sum(
            (row["sales_total"] or Decimal("0.00") for row in category_rows), Decimal("0.00")
        )
        category_rows.sort(key=lambda row: row["sales_total"], reverse=True)
        sales_by_category = [
            {
                "category": row["product__category"] or "Uncategorised",
                "sales_total": row["sales_total"] or Decimal("0.00"),
                "quantity_sold": row["quantity_sold"] or 0,
                "share": _share(row["sales_total"], category_total),
            }
            for row in category_rows
        ]

        method_labels = dict(Payment.Method.choices)
        payment_rows = list(
            monthly_payments.values("method").annotate(amount=Sum("amount")).order_by("-amount")
        )
        collected_total = sum(
            (row["amount"] or Decimal("0.00") for row in payment_rows), Decimal("0.00")
        )
        payment_mix = [
            {
                "method": row["method"],
                "label": method_labels.get(row["method"], row["method"]),
                "amount": row["amount"] or Decimal("0.00"),
                "share": _share(row["amount"], collected_total),
            }
            for row in payment_rows
        ]

        expense_rows = (
            monthly_expenses.values("category").annotate(amount=Sum("amount")).order_by("-amount")
            if is_manager
            else []
        )
        expense_total = expense_totals["total_expenses"] or Decimal("0.00")
        expenses_by_category = [
            {
                "category": row["category"],
                "amount": row["amount"] or Decimal("0.00"),
                "share": _share(row["amount"], expense_total),
            }
            for row in expense_rows
        ]

        current_week = today - timedelta(days=today.weekday())
        week_start = current_week - timedelta(weeks=7)
        weekly_aggregates = {"sales_total": Sum("total")}
        if is_manager:
            weekly_aggregates["gross_profit"] = Sum("profit")
        weekly_sales = {
            row["week"].date().isoformat(): row
            for row in sales_branch_queryset(
                Sale.objects.filter(created_at__date__gte=week_start), branch
            ).annotate(
                week=TruncWeek("created_at"),
            ).values("week").annotate(**weekly_aggregates)
        }
        weekly_collections = {
            row["week"].date().isoformat(): row["amount_collected"]
            for row in payments_branch_queryset(
                Payment.objects.filter(
                    status=Payment.Status.SUCCEEDED,
                    created_at__date__gte=week_start,
                ),
                branch,
            ).annotate(week=TruncWeek("created_at")).values("week").annotate(
                amount_collected=Sum("amount"),
            )
        }
        weekly_return_rows = branch_queryset(
            SaleReturn.objects.filter(created_at__date__gte=week_start), branch
        )
        weekly_returns = {
            row["week"].date().isoformat(): row
            for row in weekly_return_rows.annotate(week=TruncWeek("created_at"))
            .values("week").annotate(value_back=Sum("value"), refund_back=Sum("refund"))
        }
        weekly_items_back = {
            row["week"].date().isoformat(): row
            for row in SaleReturnItem.objects.filter(sale_return__in=weekly_return_rows)
            .annotate(week=TruncWeek("sale_return__created_at")).values("week").annotate(
                quantity_back=Sum("quantity"), profit_back=Sum("profit")
            )
        }
        weekly_income = []
        for offset in range(7, -1, -1):
            week = current_week - timedelta(days=offset * 7)
            sales_row = weekly_sales.get(week.isoformat(), {})
            back_row = weekly_returns.get(week.isoformat(), {})
            items_row = weekly_items_back.get(week.isoformat(), {})
            collected = weekly_collections.get(week.isoformat(), Decimal("0.00"))
            refunded = back_row.get("refund_back") or Decimal("0.00")
            weekly_income.append({
                "week_start": week.isoformat(),
                "sales_total": (
                    sales_row.get("sales_total") or Decimal("0.00")
                ) - (back_row.get("value_back") or Decimal("0.00")),
                "gross_profit": (
                    sales_row.get("gross_profit") or Decimal("0.00")
                ) - (items_row.get("profit_back") or Decimal("0.00")),
                "amount_collected": collected - refunded,
                "amount_refunded": refunded,
            })

        gross_profit = totals.get("gross_profit") or Decimal("0.00")
        return Response({
            "month": month_start.strftime("%Y-%m"),
            # The shop's clock decides which day is "today" on the dashboard: a
            # till machine set to another zone would otherwise read the wrong row.
            "today": timezone.localdate().isoformat(),
            # Everything below is net of what came back, so the month the dashboard
            # shows is the month the shop actually kept.
            "total_sales": (totals["total_sales"] or Decimal("0.00")) - returned_value,
            "returned_value": returned_value,
            "refunded_total": refunded_total,
            "gross_profit": (gross_profit - returned_profit) if is_manager else None,
            "total_expenses": expense_total if is_manager else None,
            "net_profit": (gross_profit - returned_profit - expense_total) if is_manager else None,
            "items_sold": (totals["items_sold"] or 0) - returned_quantity,
            "top_product": product_performance[0] if product_performance else None,
            "daily_totals": sorted(daily.values(), key=lambda row: row["date"]),
            "weekly_income": weekly_income,
            "product_performance": product_performance,
            "sales_by_category": sales_by_category,
            "payment_mix": payment_mix,
            "expenses_by_category": expenses_by_category,
            "stagnant_count": stagnant_count,
            "stagnant_products": stagnant_products,
        })

    @action(
        detail=False,
        methods=["post"],
        url_path="checkout",
        throttle_classes=[CheckoutThrottle],
    )
    def checkout(self, request):
        checkout_serializer = CheckoutSerializer(data=request.data)
        checkout_serializer.is_valid(raise_exception=True)
        data = checkout_serializer.validated_data

        idempotency_key = (
            request.headers.get("Idempotency-Key")
            or data.get("idempotency_key")
            or ""
        ).strip()
        if len(idempotency_key) > 64:
            raise ValidationError({"idempotency_key": "Use 64 characters or fewer."})

        fingerprint = _request_fingerprint(request.data)
        if idempotency_key:
            existing = _receipt_queryset().filter(idempotency_key=idempotency_key).first()
            if existing:
                return _replay_or_conflict(existing, fingerprint)

        requested_branch_id = (request.data.get("branch") or "").strip()
        if requested_branch_id:
            branch = Branch.objects.filter(pk=requested_branch_id).first()
            if branch is None:
                raise ValidationError({"branch": "Unknown branch."})
            if not request.user.is_staff:
                own_branch = user_branch(request.user)
                if own_branch is None or own_branch.pk != branch.pk:
                    raise PermissionDenied("Only managers can choose a branch.")
        else:
            branch = user_branch(request.user) or main_branch()

        requested_quantities = {}
        for item in data["items"]:
            product_id = item["product"].id
            requested_quantities[product_id] = requested_quantities.get(product_id, 0) + item["quantity"]

        try:
            with transaction.atomic():
                locked_products = {
                    product.id: product
                    for product in Product.objects.select_for_update()
                    .filter(id__in=requested_quantities)
                    .order_by("id")
                }
                for product_id, quantity in requested_quantities.items():
                    product = locked_products[product_id]
                    if quantity > product.stock_quantity:
                        raise ValidationError({
                            "items": [
                                f"Only {product.stock_quantity} units of {product.name} left in stock."
                            ]
                        })
                    product_branch = product.branch or main_branch()
                    if branch and product_branch and product_branch.pk != branch.pk:
                        raise ValidationError({
                            "items": [f"{product.name} is not stocked at {branch.name}."]
                        })

                # The number on the till's screen is the shop's promise about this
                # basket. The debt is decided here, inside the same transaction as
                # the receipts that create it.
                customer = data.get("customer") or find_customer(
                    branch, phone=data.get("customer_phone") or ""
                )
                basket_total = sum(
                    (item["price_sold_at"] * item["quantity"] for item in data["items"]),
                    Decimal("0.00"),
                )
                paid_now = sum(
                    (payment["amount"] for payment in data.get("payments", [])),
                    Decimal("0.00"),
                )
                check_credit_limit(customer, basket_total - paid_now)

                receipt = SaleReceipt.objects.create(
                    branch=branch,
                    created_by=request.user if request.user.is_authenticated else None,
                    customer_name=(data.get("customer_name") or "").strip(),
                    customer_phone=(data.get("customer_phone") or "").strip(),
                    customer=customer,
                    idempotency_key=idempotency_key or None,
                    idempotency_hash=fingerprint if idempotency_key else "",
                )
                for item in data["items"]:
                    product = locked_products[item["product"].id]
                    price_sold_at = item["price_sold_at"]
                    if price_sold_at < product.cost_price:
                        raise ValidationError({
                            "items": [
                                f"Sale price for {product.name} cannot be below its wholesale "
                                f"cost of KES {product.cost_price}. The retail price is only a guide."
                            ]
                        })
                    Sale.objects.create(
                        receipt=receipt,
                        product=product,
                        quantity=item["quantity"],
                        price_sold_at=price_sold_at,
                    )

                for product_id, quantity in requested_quantities.items():
                    product = locked_products[product_id]
                    # The check above ran on the row this transaction read; another
                    # till may have taken units since. This is the statement that
                    # actually decides whether the goods were available.
                    if move_stock(product, -quantity) is None:
                        raise ValidationError({
                            "items": [
                                f"{product.name} ran out while this sale was being written - "
                                "another till took the last units. Adjust the basket and try again."
                            ]
                        })
                    # Only the queue is written here. The message itself is sent
                    # by `deliver_alerts` on a schedule, so Twilio never sits
                    # between a cashier and a finished sale.
                    _queue_restock_alert(product)

                for payment_data in data.get("payments", []):
                    Payment.objects.create(
                        receipt=receipt,
                        created_by=request.user if request.user.is_authenticated else None,
                        **payment_data,
                    )

        except IntegrityError as error:
            if idempotency_key:
                existing = _receipt_queryset().filter(idempotency_key=idempotency_key).first()
                if existing:
                    return _replay_or_conflict(existing, fingerprint)
            raise error

        receipt = _receipt_queryset().get(pk=receipt.pk)
        return Response(SaleReceiptSerializer(receipt).data, status=status.HTTP_201_CREATED)

    def perform_create(self, serializer):
        with transaction.atomic():
            requested_product = serializer.validated_data["product"]
            quantity = serializer.validated_data["quantity"]
            product = Product.objects.select_for_update().get(pk=requested_product.pk)

            if quantity > product.stock_quantity:
                raise ValidationError({
                    "quantity": [
                        f"Only {product.stock_quantity} units of {product.name} left in stock."
                    ]
                })
            if serializer.validated_data["price_sold_at"] < product.cost_price:
                raise ValidationError({
                    "price_sold_at": [
                        f"Sale price cannot be below the cost price of {product.cost_price}."
                    ]
                })

            sale = serializer.save(product=product)
            if move_stock(product, -sale.quantity) is None:
                raise ValidationError({
                    "quantity": [
                        f"{product.name} ran out while this sale was being written - "
                        "another till took the last units."
                    ]
                })
            _queue_restock_alert(product)


class SaleReceiptViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = SaleReceiptSerializer

    def get_queryset(self):
        queryset = _receipt_queryset()
        params = self.request.query_params
        branch = _branch_scope(self.request.user, params.get("branch"))
        queryset = branch_queryset(queryset, branch)

        # A closed period leaves the day-to-day list, not the books: the totals,
        # the credit ledger and the receipt itself keep counting it. Only the
        # super admin can ask for the archived rows back.
        if not (params.get("include_closed") in {"1", "true", "yes"} and self.request.user.is_superuser):
            queryset = queryset.filter(closed_at__isnull=True)

        period_start, period_end = _period_range(params)
        start_date = parse_date(params.get("start_date") or "")
        end_date = parse_date(params.get("end_date") or "")
        if params.get("start_date") and not start_date:
            raise ValidationError({"start_date": "Use YYYY-MM-DD format."})
        if params.get("end_date") and not end_date:
            raise ValidationError({"end_date": "Use YYYY-MM-DD format."})
        # A named period is the shop's own answer to "today", so it outranks any
        # dates the till computed from its own clock.
        if period_start or period_end:
            start_date, end_date = period_start, period_end
        if start_date:
            queryset = queryset.filter(created_at__date__gte=start_date)
        if end_date:
            queryset = queryset.filter(created_at__date__lte=end_date)
        if start_date and end_date and start_date > end_date:
            raise ValidationError({"end_date": "End date must be on or after start date."})

        search = (params.get("q") or "").strip()
        if search:
            queryset = queryset.filter(
                Q(customer_name__icontains=search) | Q(customer_phone__icontains=search)
            )

        status_filter = params.get("status")
        # Mirrors SaleReceipt.payment_status so a tab count and the badge on the row
        # can never disagree: settled bills are paid even with a prompt still open.
        # The net, not the billed total - goods that came back are no longer owed.
        if status_filter == "paid":
            queryset = queryset.filter(annotated_amount_paid__gte=F("annotated_net_total"))
        elif status_filter == "partially_paid":
            queryset = queryset.filter(
                annotated_pending_count=0,
                annotated_amount_paid__gt=0,
                annotated_amount_paid__lt=F("annotated_net_total"),
            )
        elif status_filter == "on_credit":
            queryset = queryset.filter(
                annotated_pending_count=0,
                annotated_amount_paid=0,
                annotated_net_total__gt=0,
            )
        elif status_filter == "payment_pending":
            queryset = queryset.filter(
                annotated_pending_count__gt=0,
                annotated_amount_paid__lt=F("annotated_net_total"),
            )
        elif status_filter:
            raise ValidationError({"status": "Use paid, partially_paid, on_credit or payment_pending."})
        return queryset

    @action(detail=False, methods=["get"], url_path="export")
    def export(self, request):
        response = HttpResponse(content_type="text/csv; charset=utf-8")
        today = timezone.localdate().isoformat()
        response["Content-Disposition"] = f'attachment; filename="transactions-{today}.csv"'
        response.write("\ufeff")
        writer = csv.writer(response)

        # Sums come out of the database without the trailing zeros a column of
        # takings is expected to line up on.
        def money(value):
            return f"{Decimal(value or 0):.2f}"

        writer.writerow([
            "Date", "Receipt", "Customer", "Phone", "Branch", "Served by",
            "Items", "Total (KES)", "Returned (KES)", "Paid (KES)", "Refunded (KES)",
            "Collected (KES)", "Balance (KES)", "Status", "Payment methods",
        ])
        for receipt in self.get_queryset().prefetch_related("items", "payments", "returns"):
            methods = ", ".join(
                sorted({payment.get_method_display() for payment in receipt.payments.all()})
            )
            writer.writerow([
                timezone.localtime(receipt.created_at).strftime("%Y-%m-%d %H:%M"),
                str(receipt.id)[:8].upper(),
                receipt.customer_name,
                receipt.customer_phone,
                receipt.branch.name if receipt.branch else "Main shop",
                (receipt.created_by.get_full_name() or receipt.created_by.get_username())
                if receipt.created_by else "",
                receipt.items.count(),
                money(receipt.total),
                money(receipt.returned_total),
                money(receipt.amount_paid),
                # The drawer only ever held the difference: cash that went back with
                # the goods never stayed in it.
                money(receipt.refunded_total),
                money(receipt.amount_paid - receipt.refunded_total),
                money(receipt.balance),
                receipt.payment_status.replace("_", " "),
                methods,
            ])
        return response

    @action(detail=False, methods=["get"], url_path="credits")
    def credits(self, request):
        receipts = self.get_queryset().filter(
            annotated_net_total__gt=0,
            annotated_amount_paid__lt=F("annotated_net_total"),
        )
        credit_records = []
        customer_keys = set()
        outstanding_total = Decimal("0.00")
        for receipt in receipts:
            balance = receipt.balance
            if balance <= 0:
                continue
            record = SaleReceiptSerializer(receipt).data
            credit_records.append(record)
            outstanding_total += balance
            customer_keys.add(receipt.customer_phone or receipt.customer_name or str(receipt.id))
        return Response({
            "outstanding_total": outstanding_total,
            "customer_count": len(customer_keys),
            "receipt_count": len(credit_records),
            "credits": credit_records,
        })

    @action(
        detail=False,
        methods=["post"],
        url_path="close-period",
        permission_classes=[IsAuthenticated, IsSuperUser],
    )
    def close_period(self, request):
        """Put a finished stretch of trading away without destroying any of it."""
        end_date = parse_date(str(request.data.get("end_date") or ""))
        if not end_date:
            raise ValidationError({"end_date": "Use YYYY-MM-DD format."})
        start_date = parse_date(str(request.data.get("start_date") or ""))
        if request.data.get("start_date") and not start_date:
            raise ValidationError({"start_date": "Use YYYY-MM-DD format."})
        if start_date and start_date > end_date:
            raise ValidationError({"end_date": "End date must be on or after start date."})
        undo = str(request.data.get("undo") or "").lower() in {"1", "true", "yes"}
        today = timezone.localdate()
        if not undo and end_date >= today:
            raise ValidationError({
                "end_date": "Today is still being traded. Close a period that has already ended."
            })

        branch = _branch_scope(request.user, request.data.get("branch"))
        queryset = branch_queryset(_receipt_queryset(), branch)
        window = {"created_at__date__lte": end_date}
        if start_date:
            window["created_at__date__gte"] = start_date

        if undo:
            reopened = queryset.filter(closed_at__isnull=False, **window).update(
                closed_at=None, closed_by=None
            )
            return Response({"reopened": reopened, "end_date": end_date.isoformat()})

        # Anything still owed stays in the list. A debt that has been archived is a
        # debt nobody is looking at, and closing a period must never lose money.
        owing_ids = list(
            queryset.filter(closed_at__isnull=True, **window)
            .filter(annotated_amount_paid__lt=F("annotated_net_total"))
            .values_list("id", flat=True)
        )
        settled_count = queryset.filter(closed_at__isnull=True, **window).exclude(
            pk__in=owing_ids
        ).update(closed_at=timezone.now(), closed_by=request.user)
        return Response({
            "closed": settled_count,
            "left_open": len(owing_ids),
            "start_date": start_date.isoformat() if start_date else None,
            "end_date": end_date.isoformat(),
        })

    @action(
        detail=True,
        methods=["post"],
        url_path="stk-push",
        throttle_classes=[StkPushThrottle],
    )
    def stk_push(self, request, pk=None):
        push_serializer = StkPushSerializer(data=request.data)
        push_serializer.is_valid(raise_exception=True)
        data = push_serializer.validated_data

        try:
            phone = normalize_phone(data["phone"])
        except MpesaError as error:
            raise ValidationError({"phone": [str(error)]}) from error

        with transaction.atomic():
            receipt = SaleReceipt.objects.select_for_update().get(pk=pk)
            _assert_receipt_access(request.user, receipt)
            receipt.expire_stale_stk_payments()
            if receipt.payments.filter(unresolved_stk_prompts()).exists():
                raise ValidationError({
                    "payment": (
                        "An earlier M-Pesa prompt on this bill has not been answered yet. "
                        "Use Check status first: only Safaricom can say whether that prompt "
                        "went through, and a second one would ask the customer to pay twice."
                    )
                })
            amount = data.get("amount", receipt.balance)
            if amount <= 0:
                raise ValidationError({"amount": "This receipt has no outstanding balance."})
            if amount > receipt.balance:
                raise ValidationError({"amount": f"The outstanding balance is {receipt.balance}."})

            # Daraja only accepts whole shillings. Round down so we never ask for
            # more than the customer owes; any cents remain on the receipt.
            stk_amount = amount.quantize(Decimal("1"), rounding=ROUND_HALF_UP)
            if stk_amount > amount:
                stk_amount = amount.quantize(Decimal("1"), rounding=ROUND_DOWN)
            if stk_amount < 1:
                raise ValidationError({"amount": "M-Pesa payments must be at least KES 1."})

            payment = Payment.objects.create(
                receipt=receipt,
                created_by=request.user if request.user.is_authenticated else None,
                amount=stk_amount,
                method=Payment.Method.MPESA_STK,
                status=Payment.Status.PENDING,
            )

        try:
            response = initiate_stk_push(payment, phone)
            if str(response.get("ResponseCode")) != "0":
                raise MpesaError(response.get("ResponseDescription", "Safaricom did not accept the STK request."))
            checkout_request_id = response.get("CheckoutRequestID")
            if not checkout_request_id:
                raise MpesaError("Safaricom accepted no checkout request ID; payment status is unknown.")
        except MpesaUnconfirmed as error:
            # Safaricom may have taken the prompt even though it never answered.
            # The row is closed because there is no request ID to query, but the
            # till is told it is unconfirmed rather than "nothing was charged".
            payment.status = Payment.Status.FAILED
            payment.result_description = str(error)[:255]
            payment.save(update_fields=["status", "result_description"])
            return Response(
                {"detail": str(error), "confirmed": False},
                status=status.HTTP_400_BAD_REQUEST,
            )
        except MpesaError as error:
            payment.status = Payment.Status.FAILED
            payment.result_description = str(error)[:255]
            payment.save(update_fields=["status", "result_description"])
            raise serializers.ValidationError({"payment": [str(error)]}) from error

        payment.checkout_request_id = checkout_request_id
        payment.merchant_request_id = response.get("MerchantRequestID", "")[:100]
        payment.result_description = response.get("CustomerMessage", "STK prompt sent")[:255]
        payment.save(update_fields=["checkout_request_id", "merchant_request_id", "result_description"])

        receipt = _receipt_queryset().get(pk=pk)
        return Response({
            "message": payment.result_description,
            "amount": str(stk_amount),
            "receipt": SaleReceiptSerializer(receipt).data,
        }, status=status.HTTP_202_ACCEPTED)

    @action(
        detail=True,
        methods=["post"],
        url_path="check-payment",
        throttle_classes=[PaymentThrottle],
    )
    def check_payment(self, request, pk=None):
        """Settle an M-Pesa prompt the callback never finished and report the outcome."""
        with transaction.atomic():
            receipt = SaleReceipt.objects.select_for_update().get(pk=pk)
            _assert_receipt_access(request.user, receipt)
            receipt.expire_stale_stk_payments()
            pending = receipt.payments.filter(
                method=Payment.Method.MPESA_STK,
                status=Payment.Status.PENDING,
            ).order_by("-created_at").first()
            if pending and not pending.checkout_request_id:
                pending.status = Payment.Status.FAILED
                pending.result_description = (
                    "Timed out before Safaricom returned a checkout request ID."
                )
                pending.save(update_fields=["status", "result_description"])
                pending = None

        note = ""
        if pending is not None:
            # Daraja is asked outside the lock so a slow reply never holds up the
            # rest of the counter.
            try:
                outcome, description, reference = apply_query_result(
                    pending, query_stk_push(pending)
                )
            except MpesaError as error:
                note = str(error)
            else:
                if outcome is None:
                    note = description
                else:
                    with transaction.atomic():
                        # Re-read: the callback may have landed while querying Daraja.
                        payment = Payment.objects.select_for_update().get(pk=pending.pk)
                        if payment.status == Payment.Status.PENDING:
                            payment.status = outcome
                            payment.result_description = description
                            fields = ["status", "result_description"]
                            if reference and not payment.reference:
                                payment.reference = reference
                                fields.append("reference")
                            payment.save(update_fields=fields)

        fresh = _receipt_queryset().get(pk=pk)
        data = SaleReceiptSerializer(fresh).data
        prompts = [
            entry for entry in data["payments"]
            if entry["method"] == Payment.Method.MPESA_STK
        ]
        latest = prompts[-1] if prompts else None
        payment_status = data["payment_status"]

        if payment_status == "paid":
            state = "paid"
        elif payment_status == "payment_pending":
            state = "waiting"
        else:
            state = "not_paid"

        return Response({
            "state": state,
            "balance": data["balance"],
            "amount_paid": data["amount_paid"],
            "mpesa_code": (latest or {}).get("reference", ""),
            "result_description": (latest or {}).get("result_description", ""),
            "note": note,
            "receipt": data,
        })

    @action(
        detail=True,
        methods=["post"],
        url_path="payments",
        throttle_classes=[PaymentThrottle],
    )
    def payments(self, request, pk=None):
        payment_serializer = ReceiptPaymentSerializer(data=request.data)
        payment_serializer.is_valid(raise_exception=True)

        with transaction.atomic():
            receipt = SaleReceipt.objects.select_for_update().get(pk=pk)
            _assert_receipt_access(request.user, receipt)
            receipt.expire_stale_stk_payments()
            payment_data = payment_serializer.validated_data
            if payment_data["amount"] > receipt.balance:
                raise ValidationError({"amount": [f"The outstanding balance is {receipt.balance}."]})
            Payment.objects.create(
                receipt=receipt,
                created_by=request.user if request.user.is_authenticated else None,
                **payment_data,
            )

        receipt = _receipt_queryset().get(pk=pk)
        return Response(SaleReceiptSerializer(receipt).data, status=status.HTTP_201_CREATED)

    @action(
        detail=True,
        methods=["post"],
        url_path="returns",
        permission_classes=[IsAuthenticated, IsManager],
        throttle_classes=[PaymentThrottle],
    )
    def returns(self, request, pk=None):
        """Take goods back off the customer and put the money right beside them.

        Nothing on the original bill is touched. A return row says what came back and
        what was handed over for it, the shelf is topped up in the same write, and
        every figure the counter reads afterwards - balance, credit book, today's
        takings - is worked out from both rows.
        """
        return_serializer = ReturnCreateSerializer(data=request.data)
        return_serializer.is_valid(raise_exception=True)
        data = return_serializer.validated_data

        idempotency_key = (
            request.headers.get("Idempotency-Key")
            or data.get("idempotency_key")
            or ""
        ).strip()
        if len(idempotency_key) > 64:
            raise ValidationError({"idempotency_key": "Use 64 characters or fewer."})
        fingerprint = _request_fingerprint(request.data)

        def replay():
            existing = SaleReturn.objects.prefetch_related(
                "items__product", "receipt"
            ).filter(idempotency_key=idempotency_key).first()
            if not existing:
                return None
            if existing.idempotency_hash and existing.idempotency_hash != fingerprint:
                raise IdempotencyConflict()
            return Response(
                SaleReceiptSerializer(_receipt_queryset().get(pk=existing.receipt_id)).data,
                status=status.HTTP_200_OK,
            )

        if idempotency_key:
            answered = replay()
            if answered:
                return answered

        try:
            with transaction.atomic():
                receipt = SaleReceipt.objects.select_for_update().get(pk=pk)
                _assert_receipt_access(request.user, receipt)
                if receipt.closed_at:
                    raise ValidationError({
                        "receipt": "This bill is in a closed period. Reopen the period "
                                   "before taking goods back against it."
                    })
                if receipt.payments.filter(unresolved_stk_prompts()).exists():
                    # The customer may still be about to pay the whole old total. A
                    # return taken underneath that prompt would let money arrive for
                    # goods that already came back, with nothing to hand it over for.
                    raise ValidationError({
                        "receipt": "An M-Pesa request on this bill is still waiting for "
                                   "the customer's PIN. Let it finish or fail first, then "
                                   "take the goods back."
                    })

                lines = {sale.id: sale for sale in Sale.objects.filter(receipt=receipt).select_related("product")}
                if not lines:
                    raise ValidationError({"items": "This receipt has no lines to return."})

                asked = {}
                for item in data["items"]:
                    sale_id = item["sale"].id
                    if sale_id not in lines:
                        raise ValidationError({
                            "items": ["That line was not sold on this receipt."]
                        })
                    asked[sale_id] = asked.get(sale_id, 0) + item["quantity"]

                still_out = {}
                for row in (
                    SaleReturnItem.objects.filter(sale_id__in=asked)
                    .values("sale_id")
                    .annotate(came_back=Sum("quantity"))
                ):
                    still_out[row["sale_id"]] = row["came_back"] or 0

                value = Decimal("0.00")
                chosen = []
                for sale_id, quantity in asked.items():
                    sale = lines[sale_id]
                    returnable = sale.quantity - still_out.get(sale_id, 0)
                    if quantity > returnable:
                        raise ValidationError({
                            "items": [
                                f"Only {returnable} of the {sale.quantity} "
                                f"{sale.product.name} on this bill are still out."
                            ]
                        })
                    value += sale.price_sold_at * quantity
                    chosen.append((sale, quantity))

                # What the customer now owes, against what they actually handed in.
                # Anything left over is the shop's money in the wrong hand, and the
                # number is worked out here so it cannot be typed in at the till.
                owed_after = (
                    receipt.total - receipt.returned_total - value
                )
                refund = receipt.amount_paid - receipt.refunded_total - owed_after
                if refund < 0:
                    refund = Decimal("0.00")
                method = data.get("refund_method") or ""
                if refund > 0 and not method:
                    # A refund nobody described is still cash that left the till.
                    method = Payment.Method.CASH

                entry_return = SaleReturn.objects.create(
                    receipt=receipt,
                    branch=receipt.branch,
                    created_by=request.user if request.user.is_authenticated else None,
                    value=value,
                    refund=refund,
                    method=method,
                    reference=(data.get("reference") or "").strip(),
                    reason=(data.get("reason") or "").strip(),
                    idempotency_key=idempotency_key or None,
                    idempotency_hash=fingerprint if idempotency_key else "",
                )
                for sale, quantity in chosen:
                    SaleReturnItem.objects.create(
                        sale_return=entry_return,
                        sale=sale,
                        product=sale.product,
                        quantity=quantity,
                    )
                    if move_stock(sale.product, quantity) is None:
                        raise ValidationError({
                            "items": [f"{sale.product.name} is no longer stocked, "
                                      "so these goods cannot go back on the shelf."]
                        })
        except IntegrityError:
            if idempotency_key:
                answered = replay()
                if answered:
                    return answered
            raise

        receipt = _receipt_queryset().get(pk=pk)
        return Response(SaleReceiptSerializer(receipt).data, status=status.HTTP_201_CREATED)


@api_view(["POST"])
@authentication_classes([])
@permission_classes([AllowAny])
def mpesa_callback(request):
    expected_token = config("MPESA_CALLBACK_TOKEN", default="")
    supplied_token = request.query_params.get("token", "")
    if not expected_token or not hmac.compare_digest(expected_token, supplied_token):
        return Response({"detail": "Invalid callback token."}, status=status.HTTP_403_FORBIDDEN)

    body = request.data.get("Body") if isinstance(request.data, dict) else None
    callback = body.get("stkCallback") if isinstance(body, dict) else None
    if not isinstance(callback, dict):
        return Response({"detail": "Invalid callback payload."}, status=status.HTTP_400_BAD_REQUEST)

    checkout_request_id = callback.get("CheckoutRequestID")
    if not checkout_request_id:
        return Response({"ResultCode": 0, "ResultDesc": "Ignored"}, status=status.HTTP_200_OK)

    with transaction.atomic():
        payment = Payment.objects.select_for_update().filter(
            checkout_request_id=checkout_request_id,
            method=Payment.Method.MPESA_STK,
        ).first()
        if not payment or payment.status == Payment.Status.SUCCEEDED:
            # Already settled one way or the other: a replay changes nothing. A
            # prompt this server had given up on is still open to proof, because
            # only Daraja can say whether the customer typed the PIN.
            return Response({"ResultCode": 0, "ResultDesc": "Accepted"}, status=status.HTTP_200_OK)

        result_code = callback.get("ResultCode")
        payment.result_description = str(callback.get("ResultDesc", ""))[:255]
        if str(result_code) == "0":
            metadata_items = (callback.get("CallbackMetadata") or {}).get("Item") or []
            metadata = {
                item.get("Name"): item.get("Value")
                for item in metadata_items
                if isinstance(item, dict) and item.get("Name")
            }
            raw_amount = metadata.get("Amount")
            try:
                callback_amount = Decimal(str(raw_amount)) if raw_amount is not None else None
            except (InvalidOperation, TypeError, ValueError):
                callback_amount = None
            if callback_amount is not None and callback_amount == payment.amount:
                # A prompt this server had already given up on can still be proved
                # paid - the customer typed the PIN after the till stopped waiting.
                # The money is real, so the books take it whatever the earlier guess
                # said, and the bill now shows what it over-collected.
                if payment.status == Payment.Status.FAILED:
                    logger.warning(
                        "M-Pesa callback settled prompt %s that had been marked failed; "
                        "the till must check whether the customer already paid in cash.",
                        payment.checkout_request_id,
                    )
                payment.status = Payment.Status.SUCCEEDED
                payment.reference = str(metadata.get("MpesaReceiptNumber", ""))[:100]
            else:
                payment.status = Payment.Status.FAILED
                payment.result_description = "Callback amount did not match the requested amount."
        else:
            payment.status = Payment.Status.FAILED
        payment.save(update_fields=["status", "reference", "result_description"])

    return Response({"ResultCode": 0, "ResultDesc": "Accepted"}, status=status.HTTP_200_OK)
