from PIL import Image, UnidentifiedImageError
from rest_framework import serializers

from accounts.models import Branch
from accounts.services import resolve_branch

from .models import Product
from .services import move_stock


class ProductSerializer(serializers.ModelSerializer):
    needs_restock = serializers.ReadOnlyField()
    branch_name = serializers.CharField(source="branch_label", read_only=True)
    branch = serializers.PrimaryKeyRelatedField(
        queryset=Branch.objects.all(), required=False, allow_null=True
    )
    selling_price = serializers.DecimalField(max_digits=10, decimal_places=2, required=False)
    price_floor = serializers.DecimalField(
        source="cost_price", max_digits=10, decimal_places=2, read_only=True
    )
    # The stock number the edit form was opened with. Without it, saving a new
    # price would write back the count the manager read minutes ago and erase any
    # sale that completed while the form was open.
    stock_quantity_from = serializers.IntegerField(write_only=True, required=False, min_value=0)

    def _target_branch(self, data):
        if "branch" in data:
            branch = data["branch"]
            if branch is None:
                branch = resolve_branch(self.context["request"].user)
            return branch
        if self.instance and self.instance.branch_id:
            return self.instance.branch
        return resolve_branch(self.context["request"].user)

    def validate(self, data):
        cost = data.get("cost_price", getattr(self.instance, "cost_price", None))
        selling = data.get("selling_price", getattr(self.instance, "selling_price", None))
        if cost is not None and selling is not None and selling < cost:
            raise serializers.ValidationError({
                "selling_price": "Selling price cannot be below the cost price.",
            })

        branch = self._target_branch(data)
        data["branch"] = branch

        sku = data.get("sku", getattr(self.instance, "sku", None))
        if sku:
            duplicates = Product.objects.filter(branch=branch, sku__iexact=sku.strip())
            if self.instance:
                duplicates = duplicates.exclude(pk=self.instance.pk)
            if duplicates.exists():
                raise serializers.ValidationError({
                    "sku": "This SKU already exists in the selected branch.",
                })
        return data

    def create(self, validated_data):
        validated_data.pop("stock_quantity_from", None)
        validated_data.setdefault("selling_price", validated_data["cost_price"])
        return super().create(validated_data)

    def update(self, instance, validated_data):
        counted_from = validated_data.pop("stock_quantity_from", None)
        if counted_from is None:
            return super().update(instance, validated_data)

        counted = validated_data.pop("stock_quantity", None)
        product = super().update(instance, validated_data)
        if counted is None or counted == counted_from:
            # A price-only edit never touches the shelf, so whatever the tills sold
            # while the form was open stays counted.
            return product

        moved = move_stock(product, counted - counted_from)
        if moved is None:
            raise serializers.ValidationError({
                "stock_quantity": (
                    "The stock on the system fell below this count while you were editing. "
                    "Reload the product and enter the counted number again."
                )
            })
        return moved

    def validate_image(self, image):
        allowed_extensions = {".jpg", ".jpeg", ".png", ".webp"}
        extension = "." + image.name.rsplit(".", 1)[-1].lower() if "." in image.name else ""
        if extension not in allowed_extensions:
            raise serializers.ValidationError("Choose a JPG, PNG, or WebP image.")
        if image.size > 5 * 1024 * 1024:
            raise serializers.ValidationError("Image must be 5 MB or smaller.")

        try:
            parsed = Image.open(image)
            image_format = parsed.format
            parsed.verify()
        except (UnidentifiedImageError, OSError, ValueError) as error:
            raise serializers.ValidationError("This file is not a valid image.") from error
        finally:
            image.seek(0)

        if image_format not in {"JPEG", "PNG", "WEBP"}:
            raise serializers.ValidationError("Choose a JPG, PNG, or WebP image.")
        return image

    class Meta:
        model = Product
        # SKU uniqueness is enforced per branch in validate(); DRF's automatic
        # conditional UniqueTogether validator would demand branch before we resolve it.
        validators = []
        fields = [
            "id", "branch", "branch_name", "name", "sku", "category", "image",
            "cost_price", "selling_price", "price_floor", "stock_quantity",
            "stock_quantity_from", "reorder_threshold", "needs_restock", "created_at", "updated_at",
        ]

    def to_representation(self, instance):
        data = super().to_representation(instance)
        request = self.context.get("request")
        user = getattr(request, "user", None)
        if not (user and user.is_staff):
            # Cashiers need the floor to block loss-making sales, but not the
            # wholesale cost or the margin it implies.
            data.pop("cost_price", None)
        return data
