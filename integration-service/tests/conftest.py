import os
from collections.abc import AsyncIterator
from pathlib import Path

import pytest
from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool

from hl7_integration.database.migrate import apply_migrations
from hl7_integration.hl7.parser import ParsedMessage, parse_message

SAMPLES_DIRECTORY = Path(__file__).parent.parent / "samples"
TEST_DATABASE_URL = os.environ.get("TEST_DATABASE_URL", "postgresql://localhost:5432/hl7_int_test")


@pytest.fixture
def lab_result_message_text() -> str:
    return (SAMPLES_DIRECTORY / "oru_r01_cbc.hl7").read_text()


@pytest.fixture
def parsed_lab_result_message(lab_result_message_text: str) -> ParsedMessage:
    return parse_message(lab_result_message_text)


@pytest.fixture
def invalid_message_text() -> str:
    return (SAMPLES_DIRECTORY / "oru_r01_invalid_missing_pid.hl7").read_text()


@pytest.fixture(scope="session")
async def database_pool() -> AsyncIterator[AsyncConnectionPool]:
    apply_migrations(TEST_DATABASE_URL)
    connection_pool = AsyncConnectionPool(
        conninfo=TEST_DATABASE_URL,
        min_size=1,
        max_size=30,
        kwargs={"row_factory": dict_row},
        open=False,
    )
    await connection_pool.open(wait=True)
    yield connection_pool
    await connection_pool.close()


@pytest.fixture
async def clean_database(database_pool: AsyncConnectionPool) -> AsyncConnectionPool:
    async with database_pool.connection() as connection:
        await connection.execute("TRUNCATE message_events, inbound_messages")
    return database_pool
