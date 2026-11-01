"""The customer book: accounts, their running debts, and payments against them."""

from decimal import Decimal

from django.db import transaction
from django.db.models import Q
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.response import Response

from accounts.permissions import IsManager, IsSuperUser
from accounts.services import branch_queryset, resolve_branch, sees_all_branches, user_branch

from .credit import check_credit_limit, ledger, settle_account_payment
from .models import Customer, SaleReceipt
from .serializers import CustomerPaymentSerializer, CustomerSerializer


class CustomerViewSet(viewsets.ModelViewSet):
    """Credit accounts, one per shop.

    Every cashier can read the book and add a regular to it, because the till needs
    the account the moment goods go on credit. Only a manager moves an account after
    that: a limit raised, a number corrected, an account closed.
    """

    serializer_class = CustomerSerializer
    http_method_names = ["get", "post", "patch", "put", "delete", "head", "options"]

    def get_queryset(self):
        queryset = Customer.objects.with_balances().select_related("branch")
        queryset = branch_queryset(queryset, user_branch(self.request.user))
        search = (self.request.query_params.get("search") or "").strip()
        if search:
            digits = "".join(character for character in search if character.isdigit())
            condition = Q(name__icontains=search)
            if digits:
                condition |= Q(phone__icontains=digits)
            queryset = queryset.filter(condition)
        if (self.request.query_params.get("owing") or "") in ("1", "true"):
            queryset = queryset.filter(outstanding_amount__gt=0)
        if self.action in ("list", "debtors"):
            # A closed account stays in the book for its ledger and for the money
            # still owed on it; it only leaves the till's picker.
            queryset = queryset.filter(is_active=True)
        return queryset.order_by("name")

    def get_permissions(self):
        if self.action in ("create", "list", "retrieve", "ledger", "debtors"):
            return super().get_permissions()
        if self.action == "destroy":
            return [IsSuperUser()]
        if self.action == "payments":
            # Money taken against an account is money in the till's drawer, so the
            # cashier at the counter records it; the limit itself stays a manager's.
            return super().get_permissions()
        return [IsManager()]

    def get_serializer_context(self):
        context = super().get_serializer_context()
        context["branch"] = self._branch_for_write()
        return context

    def _branch_for_write(self):
        """The shop this account belongs to, never the one the form asked for."""
        if self.request.method in ("GET", "HEAD", "OPTIONS", "DELETE"):
            return None
        return resolve_branch(self.request.user)

    def perform_create(self, serializer):
        self._assert_manager_sets_limit(serializer)
        serializer.save(branch=self._branch_for_write())

    def perform_update(self, serializer):
        self._assert_manager_sets_limit(serializer)
        serializer.save()

    def _assert_manager_sets_limit(self, serializer):
        """How much credit a customer may carry is the owner's call, not the till's."""
        if "credit_limit" not in serializer.validated_data:
            return
        if not self.request.user.is_staff:
            raise PermissionDenied("Only a manager can set or change a credit limit.")

    def destroy(self, request, *args, **kwargs):
        """Close an account, keeping it if it still owes or ever owed the shop.

        The ledger has to outlive the profile: deleting an account with receipts
        would erase proof of a debt and break the sales list beside it.
        """
        customer = self.get_object()
        if SaleReceipt.objects.filter(customer=customer).exists():
            customer.is_active = False
            customer.save(update_fields=["is_active", "updated_at"])
            return Response(
                {
                    "detail": (
                        f"{customer.name} has sales on the book, so the account was "
                        "closed for new credit instead of deleted."
                    )
                },
                status=status.HTTP_200_OK,
            )
        return super().destroy(request, *args, **kwargs)

    @action(detail=True, methods=["get"])
    def ledger(self, request, pk=None):
        """Every bill and payment on this account, oldest first."""
        customer = self.get_object()
        return Response({
            "customer": CustomerSerializer(customer, context=self.get_serializer_context()).data,
            "entries": ledger(customer),
        })

    @action(detail=True, methods=["post"])
    def payments(self, request, pk=None):
        """Take money against the account and settle the oldest bills with it."""
        payment_serializer = CustomerPaymentSerializer(data=request.data)
        payment_serializer.is_valid(raise_exception=True)
        customer = self.get_object()

        owed = customer.outstanding
        amount = payment_serializer.validated_data["amount"]
        if owed <= 0:
            raise ValidationError({"amount": [f"{customer.name} does not owe the shop anything."]})
        if amount > owed:
            raise ValidationError({
                "amount": [
                    f"{customer.name} owes {owed:.2f}. Take {owed:.2f} or less."
                ]
            })

        with transaction.atomic():
            settled, change = settle_account_payment(
                customer,
                amount,
                method=payment_serializer.validated_data["method"],
                reference=(payment_serializer.validated_data.get("reference") or "").strip(),
                taken_by=request.user if request.user.is_authenticated else None,
            )

        if not settled:
            raise ValidationError({"amount": ["The debt changed while this payment was being written."]})

        customer = Customer.objects.with_balances().get(pk=customer.pk)
        return Response({
            "customer": CustomerSerializer(customer, context=self.get_serializer_context()).data,
            "settled_receipts": [str(receipt.pk) for receipt in settled],
            "change": change,
            "still_owing": customer.outstanding,
        }, status=status.HTTP_201_CREATED)

    @action(detail=False, methods=["get"])
    def debtors(self, request):
        """Who owes the shop, largest first - the list to work down on a slow day."""
        customers = [
            customer for customer in self.get_queryset()
            if customer.outstanding > 0
        ]
        customers.sort(key=lambda customer: customer.outstanding, reverse=True)
        total = sum((customer.outstanding for customer in customers), Decimal("0.00"))
        return Response({
            "outstanding_total": total,
            "customer_count": len(customers),
            "customers": CustomerSerializer(
                customers, many=True, context=self.get_serializer_context()
            ).data,
        })
