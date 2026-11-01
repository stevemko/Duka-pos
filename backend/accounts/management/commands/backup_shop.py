"""Copy the shop's books somewhere they can still be read after the machine dies."""

import shutil
import sqlite3
from contextlib import closing
from datetime import datetime
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import connections

PREFIX = "shop-"


class Command(BaseCommand):
    help = (
        "Write a consistent copy of the database, and of the product photos, into a "
        "backup folder, then check that the copy opens."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--destination",
            default=str(settings.BASE_DIR / "backups"),
            help="Folder the copies are written to (a second disk, not the synced one).",
        )
        parser.add_argument(
            "--keep",
            type=int,
            default=30,
            help="How many dated copies to leave in the folder before the oldest go.",
        )
        parser.add_argument(
            "--without-media", action="store_true", help="Skip the product photo folder."
        )
        parser.add_argument("--dry-run", action="store_true", help="Report, write nothing.")

    def handle(self, *args, **options):
        database = connections["default"]
        if database.vendor != "sqlite":
            raise CommandError(
                "This command only copies SQLite. A hosted database is backed up by its "
                "provider (pg_dump for PostgreSQL)."
            )

        destination = Path(options["destination"])
        keep = max(1, options["keep"])
        stamp = datetime.now().strftime("%Y-%m-%d-%H%M%S")
        target = destination / f"{PREFIX}{stamp}.sqlite3"
        stale = self._stale(destination, keep)

        if options["dry_run"]:
            self.stdout.write(f"Would write {target}")
            self.stdout.write(f"Would remove {len(stale)} older copy(ies)")
            return

        destination.mkdir(parents=True, exist_ok=True)
        self._copy_database(database, target)
        self._verify(target)

        media_copied = 0
        if not options["without_media"]:
            media_copied = self._copy_media(destination)

        for old in stale:
            old.unlink()

        self.stdout.write(
            self.style.SUCCESS(
                f"Backed up to {target} ({target.stat().st_size // 1024} KB), "
                f"{media_copied} photo file(s) copied"
                + (f", {len(stale)} older copy(ies) removed." if stale else ".")
            )
        )

    def _copy_database(self, database, target):
        """Copy through SQLite's own backup API, not the filesystem.

        The server keeps writing while this runs, and a file copy can catch a page
        half-written or leave the WAL behind - either way, a book that does not
        balance. The backup API reads one consistent snapshot.
        """
        if database.connection is None:
            database.connect()
        # closing(), not `with sqlite3.connect(...)`: on Windows a database left
        # open keeps the file locked, and the next night's cleanup cannot remove it.
        with closing(sqlite3.connect(target, isolation_level=None)) as copy:
            database.connection.backup(copy)

    def _stale(self, destination, keep):
        """Copies beyond the newest `keep - 1`, so the one about to be written fits."""
        if not destination.exists():
            return []
        copies = sorted(destination.glob(f"{PREFIX}*.sqlite3"), key=lambda path: path.name)
        return copies[: max(0, len(copies) - keep + 1)]

    def _verify(self, target):
        """A backup that cannot be opened is not a backup."""
        try:
            with closing(sqlite3.connect(target)) as connection:
                result = connection.execute("PRAGMA integrity_check").fetchone()[0]
                receipts = connection.execute("SELECT COUNT(*) FROM sales_salereceipt").fetchone()[0]
        except sqlite3.Error as error:
            target.unlink(missing_ok=True)
            raise CommandError(f"The new copy at {target} is not readable: {error}") from error
        if result != "ok":
            target.unlink(missing_ok=True)
            raise CommandError(f"The new copy at {target} failed its integrity check: {result}")
        self.stdout.write(f"Copy opens cleanly; it holds {receipts} receipt(s).")

    def _copy_media(self, destination):
        media_root = Path(settings.MEDIA_ROOT)
        if not media_root.exists():
            return 0
        copied = 0
        for source in media_root.rglob("*"):
            if not source.is_file():
                continue
            copy_to = destination / "media" / source.relative_to(media_root)
            # Product photos are not rewritten the way the books are, so a file that
            # is already in the backup folder is left alone and an interrupted run
            # simply resumes where it stopped.
            if copy_to.exists() and copy_to.stat().st_mtime >= source.stat().st_mtime:
                continue
            copy_to.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, copy_to)
            copied += 1
        return copied
