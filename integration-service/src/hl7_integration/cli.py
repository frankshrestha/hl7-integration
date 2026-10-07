"""Command line entry point: ``hl7-int migrate|serve|worker|replay``."""

import argparse
import asyncio
import logging
import signal
from uuid import UUID

import uvicorn

from hl7_integration.config import Settings, get_settings
from hl7_integration.database.connection_pool import open_connection_pool
from hl7_integration.database.migrate import apply_migrations, reapply_all_migrations
from hl7_integration.forwarding.dead_letter_service import (
    replay_all_dead_lettered_messages,
    replay_dead_lettered_message,
)
from hl7_integration.forwarding.forwarding_worker import build_forwarding_worker
from hl7_integration.http.app import create_app

logger = logging.getLogger(__name__)


def main() -> None:
    argument_parser = argparse.ArgumentParser(prog="hl7-int", description=__doc__)
    subcommands = argument_parser.add_subparsers(dest="command", required=True)

    migrate_parser = subcommands.add_parser("migrate", help="Apply database migrations")
    migrate_parser.add_argument(
        "--fresh",
        action="store_true",
        help="Drop all tables and data, then apply every migration from scratch",
    )

    serve_parser = subcommands.add_parser("serve", help="Run the HTTP endpoint (and a worker)")
    serve_parser.add_argument(
        "--no-worker", action="store_true", help="Do not run the forwarding worker in-process"
    )

    subcommands.add_parser("worker", help="Run a standalone forwarding worker")

    replay_parser = subcommands.add_parser("replay", help="Re-queue dead-lettered messages")
    replay_target = replay_parser.add_mutually_exclusive_group(required=True)
    replay_target.add_argument("--id", type=UUID, help="Inbound message id to replay")
    replay_target.add_argument("--all-dead-lettered", action="store_true")

    arguments = argument_parser.parse_args()
    settings = get_settings()
    configure_logging(settings.log_level)

    match arguments.command:
        case "migrate":
            if arguments.fresh:
                applied_migrations = reapply_all_migrations(settings.database_url)
            else:
                applied_migrations = apply_migrations(settings.database_url)
            print(f"Applied migrations: {', '.join(applied_migrations) or 'none (up to date)'}")
        case "serve":
            uvicorn.run(
                create_app(settings, run_forwarding_worker=not arguments.no_worker),
                host=settings.http_host,
                port=settings.http_port,
                log_config=None,
            )
        case "worker":
            asyncio.run(run_standalone_worker(settings))
        case "replay":
            replayed_count = asyncio.run(
                replay_messages(settings, arguments.id, arguments.all_dead_lettered)
            )
            print(f"Re-queued {replayed_count} message(s)")


def configure_logging(log_level: str) -> None:
    logging.basicConfig(
        level=log_level.upper(), format="%(asctime)s %(levelname)s %(name)s: %(message)s"
    )
    logging.getLogger("httpx").setLevel(logging.WARNING)


async def run_standalone_worker(settings: Settings) -> None:
    connection_pool = await open_connection_pool(settings)
    forwarding_worker = build_forwarding_worker(settings, connection_pool)
    stop_event = asyncio.Event()
    event_loop = asyncio.get_running_loop()
    for stop_signal in (signal.SIGINT, signal.SIGTERM):
        event_loop.add_signal_handler(stop_signal, stop_event.set)
    try:
        await forwarding_worker.run_until_stopped(stop_event)
    finally:
        await forwarding_worker.close()
        await connection_pool.close()


async def replay_messages(
    settings: Settings, inbound_message_id: UUID | None, replay_all: bool
) -> int:
    connection_pool = await open_connection_pool(settings)
    try:
        if replay_all:
            return await replay_all_dead_lettered_messages(
                connection_pool, settings.delivery_max_attempts, requested_by="cli"
            )
        assert inbound_message_id is not None
        was_replayed = await replay_dead_lettered_message(
            connection_pool, inbound_message_id, settings.delivery_max_attempts, requested_by="cli"
        )
        return 1 if was_replayed else 0
    finally:
        await connection_pool.close()


if __name__ == "__main__":
    main()
