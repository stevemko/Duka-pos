"""Shared branch helpers used by products, sales and expenses."""

from django.core.exceptions import PermissionDenied
from django.db.models import Q

from .models import Branch


def main_branch():
    return (
        Branch.objects.filter(code="MAIN").first()
        or Branch.objects.filter(is_active=True).order_by("created_at").first()
        or Branch.objects.order_by("created_at").first()
    )


def user_branch(user):
    if not user or not user.is_authenticated:
        return None
    profile = getattr(user, "profile", None)
    return profile.branch if profile else None


def sees_all_branches(user):
    if not user or not user.is_authenticated:
        return False
    return bool(user.is_superuser or (user.is_staff and user_branch(user) is None))


def resolve_branch(user, requested=None):
    """Pick the branch for a new record, rejecting branch hopping by cashiers."""
    if requested is not None:
        own = user_branch(user)
        if sees_all_branches(user):
            return requested
        if not user.is_staff:
            raise PermissionDenied("Only managers can choose a branch.")
        if own is None:
            raise PermissionDenied("You can only record activity for your own branch.")
        if requested.pk != own.pk:
            raise PermissionDenied("You can only record activity for your own branch.")
        return requested
    return user_branch(user) or main_branch()


def branch_queryset(queryset, branch, field="branch"):
    """Filter by branch, treating legacy rows without a branch as the main shop."""
    if branch is None:
        return queryset
    condition = Q(**{field: branch})
    if branch.code == "MAIN":
        condition |= Q(**{f"{field}__isnull": True})
    return queryset.filter(condition)


def sales_branch_queryset(queryset, branch):
    """Sales reach a branch through their receipt, or their product for legacy rows."""
    if branch is None:
        return queryset
    condition = Q(receipt__branch=branch) | Q(receipt__isnull=True, product__branch=branch)
    if branch.code == "MAIN":
        condition |= Q(receipt__branch__isnull=True) | Q(
            receipt__isnull=True, product__branch__isnull=True
        )
    return queryset.filter(condition)


def payments_branch_queryset(queryset, branch):
    """Payments inherit the branch of the receipt they settle."""
    if branch is None:
        return queryset
    condition = Q(receipt__branch=branch)
    if branch.code == "MAIN":
        condition |= Q(receipt__branch__isnull=True)
    return queryset.filter(condition)
