from django.db import migrations, models
from django.db.models import F, Q


def populate_cost_snapshots(apps, schema_editor):
    Sale = apps.get_model("sales", "Sale")
    for sale in Sale.objects.select_related("product").iterator():
        sale.cost_price_at_sale = sale.product.cost_price
        sale.save(update_fields=["cost_price_at_sale"])


class Migration(migrations.Migration):
    dependencies = [
        ("sales", "0003_payment_checkout_request_id_and_more"),
    ]

    operations = [
        migrations.AddField(
            model_name="sale",
            name="cost_price_at_sale",
            field=models.DecimalField(decimal_places=2, editable=False, max_digits=10, null=True),
        ),
        migrations.RunPython(populate_cost_snapshots, migrations.RunPython.noop),
        migrations.AlterField(
            model_name="sale",
            name="cost_price_at_sale",
            field=models.DecimalField(decimal_places=2, editable=False, max_digits=10),
        ),
        migrations.AddConstraint(
            model_name="sale",
            constraint=models.CheckConstraint(
                condition=Q(quantity__gt=0) & Q(price_sold_at__gte=F("cost_price_at_sale")),
                name="sale_quantity_positive_and_no_loss",
            ),
        ),
    ]