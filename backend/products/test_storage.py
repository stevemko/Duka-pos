from tempfile import TemporaryDirectory
from unittest.mock import patch

from django.core.files.base import ContentFile
from django.test import SimpleTestCase, override_settings

from products.storage import ProductImageStorage


class ProductImageStorageTests(SimpleTestCase):
    @override_settings(CLOUDINARY_URL="")
    def test_blank_cloudinary_url_keeps_local_storage(self):
        with TemporaryDirectory() as media_root:
            with override_settings(MEDIA_ROOT=media_root):
                storage = ProductImageStorage()
                saved_name = storage.save("products/lamp.png", ContentFile(b"image"))

                self.assertEqual(saved_name, "products/lamp.png")
                self.assertTrue(storage.exists(saved_name))

    @override_settings(CLOUDINARY_URL="cloudinary://test:test@demo")
    @patch("products.storage.cloudinary.uploader.upload")
    def test_configured_storage_uploads_and_returns_cloudinary_url(self, upload):
        upload.return_value = {
            "public_id": "duka-pos/products/unique-image",
            "format": "png",
        }
        storage = ProductImageStorage()
        url = "https://res.cloudinary.com/demo/image/upload/unique-image.png"

        with patch(
            "products.storage.cloudinary.utils.cloudinary_url",
            return_value=(url, {}),
        ) as build_url:
            saved_name = storage.save("products/lamp.png", ContentFile(b"image"))
            result_url = storage.url(saved_name)

        self.assertEqual(saved_name, "duka-pos/products/unique-image.png")
        self.assertEqual(result_url, url)
        upload.assert_called_once()
        build_url.assert_called_once()