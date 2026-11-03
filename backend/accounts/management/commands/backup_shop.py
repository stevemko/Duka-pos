"""Copy the shop's books somewhere they can still be read after the machine dies."""

import os
import re
import shutil
import sqlite3
import subprocess
from contextlib import closing
from datetime import datetime
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import connections

PREFIX = "shop-"
# `shop-2026-11-03-013000.sqlite3` - the stamp is what groups a copy with its manifest.
STAMP_RE = re.compile(rf"^{PREFIX}(\d{{4}}-\d{{2}}-\d{{2}}-\d{{6}})\.")


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
        engine = database.vendor
        if engine == "sqlite":
            suffix, describe = "sqlite3", self._source_path(database)
        elif engine == "postgresql":
            suffix, describe = "dump", self._source_dsn(database)
        else:
            raise CommandError(
                f"Don't know how to copy a {engine} database. Hosted engines are "
                "usually backed up by their provider as well; use that alongside this."
            )

        destination = Path(options["destination"])
        keep = max(1, options["keep"])
        stamp = datetime.now().strftime("%Y-%m-%d-%H%M%S")
        target = destination / f"{PREFIX}{stamp}.{suffix}"
        stale = self._stale(destination, keep)

        if options["dry_run"]:
            self.stdout.write(f"Would write {target} from {describe}")
            self.stdout.write(f"Would remove {len(stale)} older copy(ies)")
            return

        destination.mkdir(parents=True, exist_ok=True)
        if engine == "sqlite":
            self._copy_sqlite(database, target)
            self._verify_sqlite(target)
        else:
            self._copy_postgres(database, target)
            self._verify_postgres(target)

        media_copied = 0
        if not options["without_media"]:
            media_copied = self._copy_media(destination)

        self._write_manifest(destination, stamp, target, engine, describe, media_copied)
        for old in stale:
            for path in old:
                path.unlink(missing_ok=True)

        self.stdout.write(
            self.style.SUCCESS(
                f"Backed up to {target} ({target.stat().st_size // 1024} KB), "
                f"{media_copied} photo file(s) copied"
                + (f", {len(stale)} older copy(ies) removed." if stale else ".")
            )
        )

    # Describing the source ---------------------------------------------------

    @staticmethod
    def _source_path(database):
        return str(database.settings_dict["NAME"])

    @staticmethod
    def _source_dsn(database):
        """Host and database name only. A password never belongs in a manifest."""
        conf = database.settings_dict
        host = conf.get("HOST") or "localhost"
        port = conf.get("PORT") or "5432"
        return f"postgres://{conf['USER']}@{host}:{port}/{conf['NAME']}"

    # SQLite ------------------------------------------------------------------

    def _copy_sqlite(self, database, target):
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

    def _verify_sqlite(self, target):
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

    # PostgreSQL --------------------------------------------------------------
    # Written before the shop moves engines, so the night the database becomes
    # Postgres is not the night the backup job is found to have stopped working.

    def _copy_postgres(self, database, target):
        conf = database.settings_dict
        argv = [
            "pg_dump",
            "--format=custom",
            f"--host={conf.get('HOST') or 'localhost'}",
            f"--port={conf.get('PORT') or '5432'}",
            f"--username={conf['USER']}",
            f"--dbname={conf['NAME']}",
            f"--file={target}",
        ]
        env = dict(os.environ, PGPASSWORD=conf["PASSWORD"] or "")
        self._run_tool(argv, env, target, "pg_dump")

    def _verify_postgres(self, target):
        """pg_restore --list reads the archive's table of contents.

        It proves the file is a real dump and that the sales tables are inside it,
        without needing a live database to restore into.
        """
        listing = target.with_suffix(target.suffix + ".listing")
        if not target.exists() or target.stat().st_size == 0:
            target.unlink(missing_ok=True)
            raise CommandError(
                "pg_dump finished without complaining and left no copy behind. "
                "Check the backup folder's free space and permissions."
            )
        argv = ["pg_restore", f"--list={listing}", str(target)]
        try:
            subprocess.run(argv, capture_output=True, text=True, check=True)
        except FileNotFoundError:
            raise CommandError(
                "pg_restore is not installed or not on PATH, so this copy cannot be proved readable."
            )
        except subprocess.CalledProcessError as error:
            target.unlink(missing_ok=True)
            raise CommandError(
                f"The new copy at {target} is not a readable dump: {error.stderr.strip()[:300]}"
            ) from error
        try:
            contents = listing.read_text(encoding="utf-8", errors="replace")
        except OSError as error:
            raise CommandError(f"Could not read the dump listing: {error}") from error
        finally:
            listing.unlink(missing_ok=True)
        if "sales_salereceipt" not in contents:
            target.unlink(missing_ok=True)
            raise CommandError(
                f"The new copy at {target} holds no sales tables - wrong database?"
            )
        self.stdout.write("Copy opens cleanly; the sales tables are in it.")

    @staticmethod
    def _run_tool(argv, env, target, name):
        try:
            subprocess.run(argv, env=env, capture_output=True, text=True, check=True)
        except FileNotFoundError:
            raise CommandError(
                f"{name} is not installed or not on PATH. Install the PostgreSQL client "
                "packages on the backup machine."
            )
        except subprocess.CalledProcessError as error:
            target.unlink(missing_ok=True)
            raise CommandError(f"{name} failed: {error.stderr.strip()[:300]}") from error

    # Common to both engines ---------------------------------------------------

    def _write_manifest(self, destination, stamp, target, engine, describe, media_copied):
        """Leave a note saying what the copy is and how to put it back.

        A folder of undated binaries is how a restore turns into a guess. This is
        the page the shop reads at two in the morning.
        """
        from sales.models import Payment, SaleReceipt

        if engine == "sqlite":
            restore = f"copy {target.name} over the live file, then run manage.py migrate"
        else:
            restore = f"pg_restore --clean --if-exists -d <database> {target.name}"
        manifest = destination / f"{PREFIX}{stamp}.manifest.txt"
        manifest.write_text(
            "\n".join([
                f"Shop backup {stamp}",
                f"engine: {engine}",
                f"source: {describe}",
                f"database copy: {target.name} ({target.stat().st_size} bytes)",
                f"receipts: {SaleReceipt.objects.count()}",
                f"payments: {Payment.objects.count()}",
                f"photo files copied this run: {media_copied}",
                f"photos live in: {(destination / 'media')}",
                f"restore: {restore}",
                "",
            ]),
            encoding="utf-8",
        )

    def _stale(self, destination, keep):
        """Backup sets beyond the newest `keep - 1`, so the one about to be written fits.

        A set is the copy and the manifest written with it: they are removed
        together, or the folder fills with notes describing files that are gone.
        """
        if not destination.exists():
            return []
        sets = {}
        for path in sorted(destination.glob(f"{PREFIX}*"), key=lambda p: p.name):
            match = STAMP_RE.match(path.name)
            if match:
                sets.setdefault(match.group(1), []).append(path)
        stamps = sorted(sets)
        return [sets[stamp] for stamp in stamps[: max(0, len(stamps) - keep + 1)]]

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
