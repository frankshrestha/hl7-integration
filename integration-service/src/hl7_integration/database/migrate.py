import logging
from pathlib import Path

import psycopg

MIGRATIONS_DIRECTORY = Path(__file__).parent / "migrations"
MIGRATION_ADVISORY_LOCK_KEY = 7_406_101

logger = logging.getLogger(__name__)


def reapply_all_migrations(database_url: str) -> list[str]:
    with psycopg.connect(database_url, autocommit=True) as connection:
        connection.execute("SELECT pg_advisory_lock(%s)", (MIGRATION_ADVISORY_LOCK_KEY,))
        try:
            with connection.transaction():
                connection.execute("DROP SCHEMA public CASCADE")
                connection.execute("CREATE SCHEMA public")
        finally:
            connection.execute("SELECT pg_advisory_unlock(%s)", (MIGRATION_ADVISORY_LOCK_KEY,))
    logger.warning("Dropped all database objects in the public schema")
    return apply_migrations(database_url)


def apply_migrations(database_url: str) -> list[str]:
    applied_migration_names: list[str] = []
    with psycopg.connect(database_url, autocommit=True) as connection:
        connection.execute("SELECT pg_advisory_lock(%s)", (MIGRATION_ADVISORY_LOCK_KEY,))
        try:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS schema_migrations (
                    version    text PRIMARY KEY,
                    applied_at timestamptz NOT NULL DEFAULT now()
                )
                """
            )
            already_applied = {
                row[0] for row in connection.execute("SELECT version FROM schema_migrations")
            }
            for migration_file in sorted(MIGRATIONS_DIRECTORY.glob("*.sql")):
                if migration_file.stem in already_applied:
                    continue
                with connection.transaction():
                    connection.execute(migration_file.read_text())
                    connection.execute(
                        "INSERT INTO schema_migrations (version) VALUES (%s)",
                        (migration_file.stem,),
                    )
                logger.info("Applied migration %s", migration_file.stem)
                applied_migration_names.append(migration_file.stem)
        finally:
            connection.execute("SELECT pg_advisory_unlock(%s)", (MIGRATION_ADVISORY_LOCK_KEY,))
    return applied_migration_names
