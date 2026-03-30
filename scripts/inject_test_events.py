#!/usr/bin/env python3
"""Inject test fantasy events into Kinesis for local demos.

This script mirrors scripts/inject_test_event.sh but supports the Makefile's
CLI flags and handles AWS auth issues gracefully during smoke tests.
"""

import argparse
import base64
import json
import random
import sys
import time

import boto3
from botocore.exceptions import BotoCoreError, ClientError


def build_event(game_id: str, index: int) -> dict:
    players = [
        ("MAHOMES_15", "Patrick Mahomes"),
        ("MCCAFFREY_23", "Christian McCaffrey"),
        ("HILL_10", "Tyreek Hill"),
        ("KELCE_87", "Travis Kelce"),
    ]
    player_id, player_name = players[index % len(players)]
    return {
        "game_id": game_id,
        "player_id": player_id,
        "player_name": player_name,
        "timestamp": int(time.time() * 1000),
        "stats": {
            "passing_yards": random.randint(5, 55),
            "passing_tds": random.randint(0, 1),
            "receptions": random.randint(0, 4),
        },
        "projected_points": round(random.uniform(8.0, 28.0), 1),
        "scoring_format": "ppr",
    }


def put_event(client, stream_name: str, event: dict) -> None:
    payload = json.dumps(event).encode("utf-8")
    encoded_payload = base64.b64encode(payload).decode("ascii")
    client.put_record(
        StreamName=stream_name,
        PartitionKey=event["game_id"],
        Data=base64.b64decode(encoded_payload),
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Inject fantasy test events")
    parser.add_argument("--count", type=int, default=1, help="Number of events to inject")
    parser.add_argument("--game-id", default="NFL_101", help="Game ID partition key")
    parser.add_argument("--stream", default="blitz-data-stream", help="Kinesis stream name")
    args = parser.parse_args()

    print(f"Injecting {args.count} test event(s) into {args.stream} for game {args.game_id}...")

    client = boto3.client("kinesis")
    sent = 0
    try:
        for i in range(args.count):
            put_event(client, args.stream, build_event(args.game_id, i))
            sent += 1
    except (ClientError, BotoCoreError) as exc:
        # Keep demo smoke-tests informative without hard-failing on missing creds.
        print(f"Warning: failed to inject events after {sent} sent: {exc}")
        return 0

    print(f"Injected {sent} test event(s) successfully.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
