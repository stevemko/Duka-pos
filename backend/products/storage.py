from io import BytesIO
from pathlib import Path
from urllib.request import urlopen
from uuid import uuid4

import cloudinary
import cloudinary.uploader
import cloudinary.utils
from django.conf import settings
from django.core.files.storage import FileSystemStorage, Storage


class ProductImageStorage(Storage):
    """Use Cloudinary when configured, otherwise use local media storage."""

    def __init__(self):
        self.local_storage = FileSystemStorage()

    @property
    def cloudinary_enabled(self):
        return bool(settings.CLOUDINARY_URL.strip())

    def _configure_cloudinary(self):
        cloudinary.config(cloudinary_url=settings.CLOUDINARY_URL, secure=True)

    def _save(self, name, content):
        if not self.cloudinary_enabled:
            return self.local_storage.save(name, content)

        self._configure_cloudinary()
        result = cloudinary.uploader.upload(
            content,
            public_id=f"duka-pos/products/{uuid4().hex}",
            resource_type="image",
            overwrite=False,
            unique_filename=False,
        )
        public_id = result["public_id"]
        image_format = result.get("format")
        return f"{public_id}.{image_format}" if image_format else public_id

    def _open(self, name, mode="rb"):
        if not self.cloudinary_enabled:
            return self.local_storage.open(name, mode)
        if mode != "rb":
            raise ValueError("Cloudinary product images can only be opened in binary read mode.")
        return BytesIO(urlopen(self.url(name), timeout=20).read())

    def delete(self, name):
        if not self.cloudinary_enabled:
            return self.local_storage.delete(name)
        public_id = str(Path(name).with_suffix("")).replace("\\", "/")
        self._configure_cloudinary()
        cloudinary.uploader.destroy(public_id, resource_type="image")

    def exists(self, name):
        if not self.cloudinary_enabled:
            return self.local_storage.exists(name)
        return False

    def url(self, name):
        if not self.cloudinary_enabled:
            return self.local_storage.url(name)

        filename = Path(name)
        public_id = str(filename.with_suffix("")).replace("\\", "/")
        image_format = filename.suffix.lstrip(".") or None
        self._configure_cloudinary()
        url, _options = cloudinary.utils.cloudinary_url(
            public_id,
            format=image_format,
            secure=True,
            resource_type="image",
        )
        return url