"""SQLite tuning for a shop server that has no database daemon behind it.

With the default rollback journal, one write blocks every reader: a second till,
the dashboard and the product search all queue behind a single sale. Write-ahead
logging lets readers keep working while a writer is busy, which is what a counter
with several people on it needs.
"""

from django.conf import settings
from django.core.checks import Warning, register
from django.db.backends.signals import connection_created


def _configure_sqlite(connection, **kwargs):
    if connection.vendor != "sqlite":
        return
    with connection.cursor() as cursor:
        # On an in-memory test database this answers "memory" and changes nothing.
        cursor.execute("PRAGMA journal_mode=WAL")


def apply_sqlite_settings():
    connection_created.connect(
        _configure_sqlite,
        dispatch_uid="duka_pos_sqlite_pragmas",
    )


# Folders a sync client rewrites on its own schedule.
CLOUD_SYNC_FOLDERS = ("onedrive", "dropbox", "iclouddrive", "google drive", "googledrive")


@register()
def check_database_location(app_configs, **kwargs):
    """Warn when the shop's one database file sits inside a synced folder."""
    database = settings.DATABASES["default"]
    if not database["ENGINE"].endswith("sqlite3"):
        return []

    path = str(database["NAME"]).lower()
    if not any(folder in path for folder in CLOUD_SYNC_FOLDERS):
        return []

    return [
        Warning(
            "The shop database is inside a folder a sync client uploads by itself.",
            hint=(
                "A copy taken while the server is writing gives a database that will "
                "not open. Set DATABASE_PATH to a folder outside the sync - for example "
                "C:\\ShopData\\greenlight.sqlite3 - and move the file there with the "
                "server stopped."
            ),
            id="config.W001",
        )
    ]

