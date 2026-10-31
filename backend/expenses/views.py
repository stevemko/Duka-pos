from datetime import date

from django.db.models import Count, Sum
from django.utils.dateparse import parse_date
from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from accounts.models import Branch
from accounts.permissions import IsManager
from accounts.services import branch_queryset, resolve_branch, sees_all_branches, user_branch

from .models import Expense
from .serializers import ExpenseSerializer


def _month_range(value):
    try:
        start = date.fromisoformat(f"{value}-01")
    except ValueError as error:
        raise ValidationError({"month": "Use YYYY-MM format."}) from error
    if len(value) != 7:
        raise ValidationError({"month": "Use YYYY-MM format."})
    if start.month == 12:
        end = date(start.year + 1, 1, 1)
    else:
        end = date(start.year, start.month + 1, 1)
    return start, end


def _date_param(params, name):
    raw = params.get(name)
    if not raw:
        return None
    parsed = parse_date(raw)
    if parsed is None:
        raise ValidationError({name: "Use YYYY-MM-DD format."})
    return parsed


class ExpenseViewSet(viewsets.ModelViewSet):
    serializer_class = ExpenseSerializer
    permission_classes = [IsAuthenticated, IsManager]
    http_method_names = ["get", "post", "patch", "delete", "head", "options"]

    def get_queryset(self):
        queryset = Expense.objects.select_related("branch", "recorded_by")
        queryset = branch_queryset(queryset, self._branch_filter())

        params = self.request.query_params
        if params.get("month"):
            start, end = _month_range(params["month"])
            queryset = queryset.filter(date__gte=start, date__lt=end)
        start_date = _date_param(params, "start_date")
        end_date = _date_param(params, "end_date")
        if start_date and end_date and start_date > end_date:
            raise ValidationError({"end_date": "End date must be on or after start date."})
        if start_date:
            queryset = queryset.filter(date__gte=start_date)
        if end_date:
            queryset = queryset.filter(date__lte=end_date)
        if params.get("category"):
            queryset = queryset.filter(category=params["category"])
        if params.get("search"):
            queryset = queryset.filter(description__icontains=params["search"].strip())
        return queryset

    def _branch_filter(self):
        requested = self.request.query_params.get("branch")
        user = self.request.user
        if requested == "all":
            if not sees_all_branches(user):
                raise ValidationError({"branch": "You can only view your own branch."})
            return None
        if requested:
            branch = Branch.objects.filter(pk=requested).first()
            if branch is None:
                raise ValidationError({"branch": "Unknown branch."})
            if not sees_all_branches(user) and branch != user_branch(user):
                raise ValidationError({"branch": "You can only view your own branch."})
            return branch
        return user_branch(user)

    def perform_create(self, serializer):
        branch = resolve_branch(self.request.user, serializer.validated_data.get("branch"))
        serializer.save(branch=branch, recorded_by=self.request.user)

    def perform_update(self, serializer):
        branch = serializer.validated_data.get("branch", serializer.instance.branch)
        serializer.save(branch=resolve_branch(self.request.user, branch))

    @action(detail=False, methods=["get"])
    def summary(self, request):
        queryset = self.get_queryset()
        total = queryset.aggregate(total=Sum("amount"))["total"] or 0
        by_category = list(
            queryset.values("category")
            .annotate(total=Sum("amount"), entries=Count("id"))
            .order_by("-total")
        )
        return Response({
            "total": total,
            "entries": queryset.count(),
            "by_category": by_category,
        })
