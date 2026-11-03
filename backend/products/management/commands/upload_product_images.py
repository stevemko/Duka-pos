from pathlib import Path, PurePosixPath

from django.conf import settings
from django.core.files import File
from django.core.management.base import BaseCommand, CommandError

from products.models import Product
from products.storage import ProductImageStorage


class Command(BaseCommand):
    help = "Upload existing local product photos to Cloudinary and update their database references."

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="List eligible product photos without uploading or updating anything.",
        )

    def handle(self, *args, **options):
        storage = ProductImageStorage()
        if not storage.cloudinary_enabled:
            raise CommandError("Set CLOUDINARY_URL in backend/.env before running this command.")

        media_root = Path(settings.MEDIA_ROOT).resolve()
        products = Product.objects.exclude(image="").order_by("pk")
        uploaded = skipped = missing = 0

        for product in products.iterator():
            image_name = product.image.name
            if image_name.startswith("duka-pos/products/"):
                skipped += 1
                continue

            relative_name = PurePosixPath(image_name)
            if ".." in relative_name.parts or relative_name.is_absolute():
                self.stderr.write(f"Skipped product {product.pk}: unsafe image path.")
                skipped += 1
                continue

            source = (media_root / Path(*relative_name.parts)).resolve()
            if not source.is_relative_to(media_root):
                self.stderr.write(f"Skipped product {product.pk}: image path escapes media root.")
                skipped += 1
                continue
            if not source.is_file():
                self.stderr.write(f"Missing local image for product {product.pk}.")
                missing += 1
                continue

            if options["dry_run"]:
                self.stdout.write(f"Would upload product {product.pk}: {relative_name}")
                uploaded += 1
                continue

            with source.open("rb") as image_file:
                saved_name = storage.save(
                    f"products/{product.pk}{source.suffix.lower()}",
                    File(image_file, name=source.name),
                )
            Product.objects.filter(pk=product.pk).update(image=saved_name)
            self.stdout.write(f"Uploaded product {product.pk}.")
            uploaded += 1

        action = "Would upload" if options["dry_run"] else "Uploaded"
        self.stdout.write(
            self.style.SUCCESS(
                f"{action} {uploaded} product photo(s); skipped {skipped}; missing {missing}. "
                "Original local files were left untouched."
            )
        )