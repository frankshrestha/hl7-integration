"""Postgres connection pool."""

from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool

from hl7_integration.config import Settings


async def open_connection_pool(settings: Settings) -> AsyncConnectionPool:
    connection_pool = AsyncConnectionPool(
        conninfo=settings.database_url,
        min_size=settings.database_pool_min_size,
        max_size=settings.database_pool_max_size,
        kwargs={"row_factory": dict_row, "autocommit": False},
        open=False,
        timeout=5.0,
    )
    await connection_pool.open(wait=False)
    return connection_pool
