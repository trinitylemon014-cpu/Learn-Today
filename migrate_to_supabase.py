"""
migrate_to_supabase.py

One-off migration script: copies data from the local SQLite database
(instance/database.db) into Supabase Postgres, and uploads any locally
stored media files (thumbnails, avatars, attachments, etc.) into the
Supabase Storage bucket named "media", rewriting the DB values to the
new Supabase public URLs.

USAGE
-----
    python migrate_to_supabase.py                 # dry run (no writes)
    python migrate_to_supabase.py --apply          # actually migrate

Run this from the project root (same folder as app.py), with your .env
file present and instance/database.db still on disk. Run it BEFORE you
delete instance/ or switch the app over to Supabase-only, since it needs
to read from the old SQLite file.

WHAT IT DOES
------------
1. Connects to Supabase using SUPABASE_URL + SUPABASE_SERVICE_ROLE_KEY
   (falls back to SUPABASE_ANON_KEY) from your .env file.
2. Opens instance/database.db read-only.
3. For each table, in an order that respects foreign keys:
     - reads every row
     - for any column known to hold a locally-stored file path
       (e.g. "uploads/thumbnails/xxx.png"), uploads the actual file
       from static/<path> into the Supabase "media" bucket and
       rewrites the column to the new public URL
     - upserts the row into the matching Supabase table (same table
       name, matched on id) via on_conflict='id', so re-running this
       script is safe/idempotent
4. Prints a summary of rows migrated, media files uploaded, and any
   rows or files skipped due to errors, without stopping the whole
   run on a single bad row.

WHAT IT DOES NOT DO
--------------------
- It does not delete anything from SQLite or from Supabase.
- It does not touch demo accounts already seeded by app.py — upsert
  on id means the demo rows Supabase already has will just be
  overwritten with the SQLite version if ids collide. If you'd rather
  keep the fresh Supabase demo data instead of your local copy, review
  the printed summary before trusting a --apply run in production.
"""

import argparse
import os
import sqlite3
import sys
from datetime import datetime

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

try:
    from supabase import create_client
except ImportError:
    print("ERROR: the 'supabase' package is not installed. Run: pip install supabase")
    sys.exit(1)


# ─── CONFIG ──────────────────────────────────────────────────────────────
SQLITE_PATH = os.path.join('instance', 'database.db')
LOCAL_MEDIA_ROOT = 'static'          # local files are read from static/<value>
SUPABASE_URL = os.getenv('SUPABASE_URL', '').strip()
SUPABASE_SERVICE_ROLE_KEY = os.getenv('SUPABASE_SERVICE_ROLE_KEY', '').strip()
SUPABASE_ANON_KEY = os.getenv('SUPABASE_ANON_KEY', '').strip()
SUPABASE_STORAGE_BUCKET = os.getenv('SUPABASE_STORAGE_BUCKET', 'media').strip()

# Tables in an order that respects foreign keys (parents before children).
TABLE_ORDER = [
    'users',
    'application_page_config',
    'courses',
    'site_media',
    'course_contents',
    'groups',
    'group_members',
    'enrollments',
    'progress',
    'attendance_sessions',
    'attendance',
    'scheduled_lessons',
    'calendar_events',
    'messages',
    'message_visibility',
    'message_delivery',
    'activity_logs',
    'notifications',
]

# Columns per table that may hold a locally-stored media path needing
# to be uploaded to the Supabase bucket and rewritten to a public URL.
MEDIA_COLUMNS = {
    'users': ['avatar', 'cv_path'],
    'courses': ['thumbnail'],
    'groups': ['avatar'],
    'messages': ['attachment_url'],
    'scheduled_lessons': ['poster_url'],
    'site_media': ['file_path'],
    'application_page_config': ['banner_image'],
}

# Columns that are boolean in Postgres but may be stored as 0/1 in SQLite.
BOOLEAN_COLUMNS = {
    'is_active', 'is_pinned', 'deleted_for_all', 'is_read',
}

BATCH_SIZE = 50


def connect_supabase():
    if not SUPABASE_URL or not (SUPABASE_SERVICE_ROLE_KEY or SUPABASE_ANON_KEY):
        print("ERROR: SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY (or SUPABASE_ANON_KEY) "
              "must be set in your .env file.")
        sys.exit(1)
    return create_client(SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY or SUPABASE_ANON_KEY)


def connect_sqlite():
    if not os.path.exists(SQLITE_PATH):
        print(f"ERROR: SQLite file not found at {SQLITE_PATH}. "
              "Nothing to migrate from.")
        sys.exit(1)
    conn = sqlite3.connect(SQLITE_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def table_exists(conn, table_name):
    cur = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
        (table_name,)
    )
    return cur.fetchone() is not None


def coerce_row(table_name, row_dict):
    """Light type cleanup so PostgREST doesn't choke on SQLite's loose typing."""
    for key, value in list(row_dict.items()):
        if value is None:
            continue
        if key in BOOLEAN_COLUMNS:
            row_dict[key] = bool(value)
    return row_dict


def migrate_media_file(supabase, local_value, apply_changes, stats):
    """
    Given a column value that might be a local path like
    'uploads/thumbnails/xxx.png', uploads the underlying file to the
    Supabase bucket (if not already there) and returns the new public
    URL. Values that are already full URLs are returned unchanged.
    Returns the original value unchanged if the local file can't be found.
    """
    if not local_value:
        return local_value
    if local_value.startswith(('http://', 'https://')):
        return local_value  # already remote — nothing to do

    local_path = os.path.join(LOCAL_MEDIA_ROOT, local_value)
    if not os.path.exists(local_path):
        stats['media_missing'] += 1
        print(f"  [media] WARNING: local file not found, leaving as-is: {local_path}")
        return local_value

    stats['media_found'] += 1
    if not apply_changes:
        return local_value  # dry run: don't actually upload

    try:
        with open(local_path, 'rb') as f:
            content = f.read()
        storage_path = local_value  # keep the same relative path inside the bucket
        try:
            supabase.storage.from_(SUPABASE_STORAGE_BUCKET).upload(
                storage_path, content
            )
        except Exception as exc:
            # Most likely "already exists" on a re-run — try update instead.
            if 'exists' in str(exc).lower() or 'duplicate' in str(exc).lower():
                supabase.storage.from_(SUPABASE_STORAGE_BUCKET).update(
                    storage_path, content
                )
            else:
                raise
        public_url = supabase.storage.from_(SUPABASE_STORAGE_BUCKET).get_public_url(storage_path)
        stats['media_uploaded'] += 1
        return public_url
    except Exception as exc:
        stats['media_errors'] += 1
        print(f"  [media] ERROR uploading {local_path}: {exc}")
        return local_value


def migrate_table(supabase, sqlite_conn, table_name, apply_changes, stats):
    if not table_exists(sqlite_conn, table_name):
        print(f"- {table_name}: not present in SQLite, skipping")
        return

    cur = sqlite_conn.execute(f"SELECT * FROM {table_name}")
    rows = [dict(r) for r in cur.fetchall()]
    if not rows:
        print(f"- {table_name}: 0 rows, nothing to migrate")
        return

    media_cols = MEDIA_COLUMNS.get(table_name, [])
    for row in rows:
        for col in media_cols:
            if col in row and row[col]:
                row[col] = migrate_media_file(supabase, row[col], apply_changes, stats)
        coerce_row(table_name, row)

    print(f"- {table_name}: {len(rows)} row(s) to migrate")

    if not apply_changes:
        stats['rows_would_migrate'] += len(rows)
        return

    migrated = 0
    for i in range(0, len(rows), BATCH_SIZE):
        batch = rows[i:i + BATCH_SIZE]
        try:
            supabase.table(table_name).upsert(batch, on_conflict='id').execute()
            migrated += len(batch)
        except Exception as exc:
            print(f"  [table] ERROR upserting batch into {table_name}: {exc}")
            stats['table_errors'] += 1

    stats['rows_migrated'] += migrated
    print(f"  -> upserted {migrated}/{len(rows)} row(s)")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--apply', action='store_true',
                         help='Actually perform the migration. Without this flag, '
                              'the script only reports what it would do.')
    args = parser.parse_args()

    print(f"Mode: {'APPLY (writing to Supabase)' if args.apply else 'DRY RUN (no writes)'}")
    print(f"Source SQLite file: {SQLITE_PATH}")
    print(f"Target Supabase project: {SUPABASE_URL or '(not set!)'}")
    print(f"Target storage bucket: {SUPABASE_STORAGE_BUCKET}")
    print()

    supabase = connect_supabase()
    sqlite_conn = connect_sqlite()

    stats = {
        'rows_migrated': 0,
        'rows_would_migrate': 0,
        'table_errors': 0,
        'media_found': 0,
        'media_uploaded': 0,
        'media_missing': 0,
        'media_errors': 0,
    }

    for table_name in TABLE_ORDER:
        migrate_table(supabase, sqlite_conn, table_name, args.apply, stats)

    sqlite_conn.close()

    print()
    print('─' * 50)
    print('Summary')
    print('─' * 50)
    if args.apply:
        print(f"Rows migrated:        {stats['rows_migrated']}")
    else:
        print(f"Rows that WOULD migrate (dry run): {stats['rows_would_migrate']}")
        print("Re-run with --apply to actually write to Supabase.")
    print(f"Media files found locally:   {stats['media_found']}")
    print(f"Media files uploaded:        {stats['media_uploaded']}")
    print(f"Media files missing on disk: {stats['media_missing']}")
    print(f"Media upload errors:         {stats['media_errors']}")
    print(f"Table upsert errors:         {stats['table_errors']}")

    if stats['table_errors'] or stats['media_errors']:
        print()
        print("⚠️  Some errors occurred — review the output above before trusting "
              "the migration is complete.")
        sys.exit(1)


if __name__ == '__main__':
    main()
