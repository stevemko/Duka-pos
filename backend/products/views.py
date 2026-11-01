import csv
import io
from decimal import Decimal, InvalidOperation

from django.db import transaction
from django.db.models import Count, DecimalField, ExpressionWrapper, F, ProtectedError, Q, Sum
from django.db.models.functions import Coalesce
from django.http import HttpResponse
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from accounts.models import Branch
from accounts.permissions import IsManager, IsSuperUser
from accounts.services import (
    branch_queryset,
    main_branch,
    sees_all_branches,
    user_branch,
)
from sales.models import SaleReturnItem

from .models import Product
from .permissions import IsStaffOrReadOnly
from .serializers import ProductSerializer
from .services import move_stock

ORDERING_FIELDS = {
    "name", "-name",
    "stock_quantity", "-stock_quantity",
    "selling_price", "-selling_price",
    "updated_at", "-updated_at",
}

IMPORT_COLUMNS = [
    "name", "sku", "category", "cost_price", "selling_price",
    "stock_quantity", "reorder_threshold",
]


def _decimal(value, field, row_number):
    try:
        parsed = Decimal(str(value).strip())
    except (InvalidOperation, TypeError, ValueError) as error:
        raise ValidationError(f"Row {row_number}: {field} must be a number.") from error
    if parsed < 0:
        raise ValidationError(f"Row {row_number}: {field} cannot be negative.")
    return parsed.quantize(Decimal("0.01"))


def _integer(value, field, row_number):
    try:
        parsed = int(str(value).strip() or 0)
    except (TypeError, ValueError) as error:
        raise ValidationError(f"Row {row_number}: {field} must be a whole number.") from error
    if parsed < 0:
        raise ValidationError(f"Row {row_number}: {field} cannot be negative.")
    return parsed


class ProductViewSet(viewsets.ModelViewSet):
    queryset = Product.objects.all()
    serializer_class = ProductSerializer
    permission_classes = [IsAuthenticated, IsStaffOrReadOnly]

    def _branch_scoped_queryset(self):
        queryset = Product.objects.select_related("branch")
        user = self.request.user
        requested = self.request.query_params.get("branch")

        if user.is_staff:
            if requested == "all" and sees_all_branches(user):
                return queryset
            if requested and requested != "all":
                branch = Branch.objects.filter(pk=requested).first()
                if branch is None:
                    raise ValidationError({"branch": "Unknown branch."})
                if not sees_all_branches(user) and branch != user_branch(user):
                    raise ValidationError({"branch": "You can only view your own branch."})
                return branch_queryset(queryset, branch)
            if sees_all_branches(user):
                return queryset
            return branch_queryset(queryset, user_branch(user))

        return branch_queryset(queryset, user_branch(user) or main_branch())

    def get_queryset(self):
        queryset = self._branch_scoped_queryset()
        params = self.request.query_params

        search = (params.get("q") or "").strip()
        if search:
            queryset = queryset.filter(
                Q(name__icontains=search)
                | Q(sku__icontains=search)
                | Q(category__icontains=search)
            )

        sku = (params.get("sku") or "").strip()
        if sku:
            queryset = queryset.filter(sku__iexact=sku)

        category = (params.get("category") or "").strip()
        if category:
            queryset = queryset.filter(category__iexact=category)

        if params.get("low") in {"1", "true", "yes"}:
            queryset = queryset.filter(stock_quantity__lte=F("reorder_threshold"))
        if params.get("in_stock") in {"1", "true", "yes"}:
            queryset = queryset.filter(stock_quantity__gt=0)

        ordering = params.get("ordering") or "name"
        if ordering not in ORDERING_FIELDS:
            ordering = "name"
        if ordering == "name":
            return queryset.order_by("name")
        return queryset.order_by(ordering, "name")

    def destroy(self, request, *args, **kwargs):
        try:
            return super().destroy(request, *args, **kwargs)
        except ProtectedError:
            return Response(
                {
                    "detail": (
                        "This product has recorded sales and cannot be deleted. "
                        "Set its stock to zero instead."
                    )
                },
                status=status.HTTP_409_CONFLICT,
            )

    @staticmethod
    def _shop_key(product):
        """Legacy products stored without a branch row still belong to the main shop."""
        if product.branch_id:
            return product.branch_id
        main = main_branch()
        return main.pk if main and main.code == "MAIN" else None

    @action(detail=True, methods=["post"], permission_classes=[IsAuthenticated, IsSuperUser])
    def merge(self, request, pk=None):
        """Collapse a product entered twice under different names into the one to keep."""
        source = self.get_object()
        target_pk = (request.data.get("target") or "").strip()
        if not target_pk:
            raise ValidationError({"target": "Choose the product to keep."})

        target = Product.objects.filter(pk=target_pk).first()
        if target is None:
            raise ValidationError({"target": "Unknown product."})
        if target.pk == source.pk:
            raise ValidationError({"target": "Choose a different product to keep."})
        if self._shop_key(source) != self._shop_key(target):
            raise ValidationError({"target": "Both products must belong to the same shop."})

        with transaction.atomic():
            locked = {
                product.pk: product
                for product in Product.objects.select_for_update()
                .filter(pk__in=[source.pk, target.pk])
                .order_by("id")
            }
            source, target = locked[source.pk], locked[target.pk]
            sales_moved = source.sales.update(product=target)
            # Goods the shop already took back are part of the same shelf item's
            # history, so they move with the sales. Left behind, they would protect
            # the duplicate row and the merge could not finish.
            returns_moved = SaleReturnItem.objects.filter(product=source).update(product=target)
            stock_moved = source.stock_quantity
            if stock_moved:
                move_stock(target, stock_moved)
            # Restock alerts for the duplicate are dropped with it; the next sale
            # re-triggers one against the product that was kept.
            source.delete()

        payload = {
            "merged_name": source.name,
            "into": ProductSerializer(target, context={"request": request}).data,
            "sales_moved": sales_moved,
            "returns_moved": returns_moved,
            "stock_moved": stock_moved,
        }
        if (source.cost_price, source.selling_price) != (target.cost_price, target.selling_price):
            payload["price_note"] = (
                "The moved stock is now priced as the kept product. Update its prices "
                "if the two entries were bought or sold at different rates."
            )
        return Response(payload)

    @action(detail=False, methods=["get"])
    def low_stock(self, request):
        low_stock_products = self.get_queryset().filter(
            stock_quantity__lte=F("reorder_threshold")
        )
        serializer = self.get_serializer(low_stock_products, many=True)
        return Response(serializer.data)

    @action(detail=False, methods=["get"])
    def categories(self, request):
        rows = (
            self._branch_scoped_queryset()
            .exclude(category="")
            .values("category")
            .annotate(products=Count("id"))
            .order_by("category")
        )
        return Response(list(rows))

    @action(detail=False, methods=["get"])
    def overview(self, request):
        queryset = self._branch_scoped_queryset()
        money_field = DecimalField(max_digits=16, decimal_places=2)
        zero = Decimal("0.00")
        totals = queryset.aggregate(
            products=Count("id"),
            units=Coalesce(Sum("stock_quantity"), 0),
            low=Count("id", filter=Q(stock_quantity__lte=F("reorder_threshold"))),
            cost_value=Coalesce(
                Sum(ExpressionWrapper(F("cost_price") * F("stock_quantity"), output_field=money_field)),
                zero,
            ),
            retail_value=Coalesce(
                Sum(ExpressionWrapper(F("selling_price") * F("stock_quantity"), output_field=money_field)),
                zero,
            ),
        )
        if not request.user.is_staff:
            # Wholesale cost totals stay behind the manager role.
            totals["cost_value"] = None
        return Response(totals)

    @action(
        detail=False,
        methods=["post"],
        url_path="import",
        url_name="import",
        permission_classes=[IsAuthenticated, IsManager],
    )
    def import_products(self, request):
        upload = request.FILES.get("file")
        if upload is None:
            raise ValidationError({"file": "Choose a CSV file to import."})
        if upload.size > 5 * 1024 * 1024:
            raise ValidationError({"file": "The CSV file must be 5 MB or smaller."})

        branch_id = (request.data.get("branch") or "").strip()
        if branch_id:
            branch = Branch.objects.filter(pk=branch_id).first()
            if branch is None:
                raise ValidationError({"branch": "Unknown branch."})
            if not sees_all_branches(request.user) and branch != user_branch(request.user):
                raise PermissionDenied("You can only import stock for your own branch.")
        else:
            branch = user_branch(request.user) or main_branch()

        try:
            text = upload.read().decode("utf-8-sig")
        except UnicodeDecodeError as error:
            raise ValidationError({"file": "Save the file as UTF-8 CSV."}) from error

        reader = csv.DictReader(io.StringIO(text))
        headers = {(header or "").strip().lower() for header in (reader.fieldnames or [])}
        missing = {"name", "cost_price"} - headers
        if missing:
            raise ValidationError({
                "file": f"Missing required columns: {', '.join(sorted(missing))}."
            })

        existing_skus = {
            sku.strip().lower()
            for sku in branch_queryset(Product.objects.all(), branch)
            .exclude(sku__isnull=True)
            .values_list("sku", flat=True)
            if sku and sku.strip()
        }
        seen_skus = set()
        to_create = []
        errors = []
        skipped = 0
        for row_number, row in enumerate(reader, start=2):
            if row_number > 5002:
                errors.append({"row": row_number, "message": "Import limited to 5000 rows per file."})
                break
            values = {
                (key or "").strip().lower(): (value or "").strip()
                for key, value in row.items()
            }
            name = values.get("name", "")
            if not name:
                skipped += 1
                continue
            try:
                if len(name) > 200:
                    raise ValidationError(f"Row {row_number}: name is longer than 200 characters.")
                sku = values.get("sku", "") or None
                if sku and len(sku) > 50:
                    raise ValidationError(f"Row {row_number}: SKU is longer than 50 characters.")
                sku_key = sku.lower() if sku else None
                if sku_key and (sku_key in existing_skus or sku_key in seen_skus):
                    raise ValidationError(f"Row {row_number}: SKU {sku} already exists in this branch.")
                cost = _decimal(values.get("cost_price"), "cost_price", row_number)
                selling_raw = values.get("selling_price")
                selling = (
                    _decimal(selling_raw, "selling_price", row_number)
                    if selling_raw
                    else cost
                )
                if selling < cost:
                    raise ValidationError(
                        f"Row {row_number}: retail price cannot be below wholesale cost."
                    )
                stock = _integer(values.get("stock_quantity"), "stock_quantity", row_number)
                reorder = _integer(values.get("reorder_threshold"), "reorder_threshold", row_number)
            except ValidationError as error:
                detail = error.detail
                if isinstance(detail, (list, tuple)) and detail:
                    detail = detail[0]
                errors.append({"row": row_number, "message": str(detail)})
                continue

            if sku_key:
                seen_skus.add(sku_key)
            to_create.append(Product(
                branch=branch,
                name=name,
                sku=sku,
                category=values.get("category", "")[:100],
                cost_price=cost,
                selling_price=selling,
                stock_quantity=stock,
                reorder_threshold=reorder,
            ))

        if to_create:
            # bulk_create sends the rows in batches, so a database hiccup halfway
            # through would leave the shop with part of its price list loaded. The
            # retry would then reject every SKU it already wrote. All of the file,
            # or none of it.
            with transaction.atomic():
                Product.objects.bulk_create(to_create, batch_size=200)

        return Response({
            "created": len(to_create),
            "skipped": skipped,
            "errors": errors[:100],
            "error_count": len(errors),
            "branch": branch.name,
        }, status=status.HTTP_201_CREATED)

    @action(detail=False, methods=["get"], url_path="import-template")
    def import_template(self, request):
        response = HttpResponse(content_type="text/csv; charset=utf-8")
        response["Content-Disposition"] = 'attachment; filename="greenlight-products-template.csv"'
        response.write("\ufeff")
        writer = csv.writer(response)
        writer.writerow(IMPORT_COLUMNS)
        writer.writerow(["LED bulb 9W", "LED-9W", "Bulbs", "180.00", "250.00", "50", "10"])
        return response
