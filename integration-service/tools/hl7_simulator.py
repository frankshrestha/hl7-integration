"""HL7 sender simulator: sends messages to the HTTP endpoint and prints ACKs.

Examples:
  uv run python -m tools.hl7_simulator samples/oru_r01_cbc.hl7
  uv run python -m tools.hl7_simulator samples/oru_r01_cbc.hl7 --count 20 --concurrency 20
  uv run python -m tools.hl7_simulator samples/oru_r01_cbc.hl7 --count 5 --unique-control-ids
"""

import argparse
import asyncio
import collections
import re
import uuid
from pathlib import Path

import httpx

ACKNOWLEDGMENT_CODE_PATTERN = re.compile(r"(?:^|\r)MSA\|(\w+)\|")


def load_message(message_path: Path) -> str:
    """Read an HL7 file and normalize segment terminators to carriage returns."""
    raw_text = message_path.read_text(encoding="utf-8")
    segment_lines = [line for line in re.split(r"\r\n|\r|\n", raw_text) if line.strip()]
    return "\r".join(segment_lines) + "\r"


def with_unique_control_id(message: str) -> str:
    header_line, _, remaining_segments = message.partition("\r")
    header_fields = header_line.split("|")
    header_fields[9] = f"SIM{uuid.uuid4().hex[:12].upper()}"
    return "|".join(header_fields) + "\r" + remaining_segments


async def send_over_http(http_client: httpx.AsyncClient, url: str, message: str) -> str:
    response = await http_client.post(
        url, content=message.encode(), headers={"Content-Type": "application/hl7-v2"}
    )
    return response.text


def extract_acknowledgment_code(acknowledgment_message: str) -> str:
    match = ACKNOWLEDGMENT_CODE_PATTERN.search(acknowledgment_message)
    return match.group(1) if match else "NO_ACK"


async def run_simulation(arguments: argparse.Namespace) -> None:
    base_message = load_message(arguments.message_file)
    concurrency_limiter = asyncio.Semaphore(arguments.concurrency)
    acknowledgment_counts: collections.Counter[str] = collections.Counter()

    async with httpx.AsyncClient(timeout=30.0) as http_client:

        async def send_one(sequence_number: int) -> None:
            message = (
                with_unique_control_id(base_message)
                if arguments.unique_control_ids
                else base_message
            )
            async with concurrency_limiter:
                try:
                    acknowledgment = await send_over_http(http_client, arguments.http_url, message)
                except httpx.HTTPError as send_error:
                    acknowledgment = f"SEND FAILED: {send_error!r}"
            acknowledgment_counts[extract_acknowledgment_code(acknowledgment)] += 1
            if arguments.count == 1 or arguments.verbose:
                print(f"--- ACK #{sequence_number}")
                print(acknowledgment.replace("\r", "\n").strip())

        await asyncio.gather(*(send_one(number) for number in range(1, arguments.count + 1)))

    print(f"Sent {arguments.count} message(s); ACK codes: {dict(acknowledgment_counts)}")


def main() -> None:
    argument_parser = argparse.ArgumentParser(description=__doc__)
    argument_parser.add_argument("message_file", type=Path)
    argument_parser.add_argument("--http-url", default="http://127.0.0.1:8085/hl7/messages")
    argument_parser.add_argument("--count", type=int, default=1)
    argument_parser.add_argument("--concurrency", type=int, default=1)
    argument_parser.add_argument("--unique-control-ids", action="store_true")
    argument_parser.add_argument("--verbose", action="store_true")
    asyncio.run(run_simulation(argument_parser.parse_args()))


if __name__ == "__main__":
    main()
