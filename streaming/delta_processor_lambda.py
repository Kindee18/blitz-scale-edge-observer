import asyncio
import base64
import json
import logging
import os
import sys
from typing import Dict, Optional

import aioredis
import boto3
from aws_xray_sdk.core import patch_all, xray_recorder
from botocore.config import Config
from opentelemetry import trace
from opentelemetry.instrumentation.botocore import BotocoreInstrumentor
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor, ConsoleSpanExporter
from pydantic import BaseModel, validator

# Add streaming directory to path for imports
sys.path.insert(0, os.path.dirname(__file__))
from fantasy_scoring import calculate_fantasy_delta, generate_start_sit_signal

_instrumented = False


def setup_instrumentation():
    global _instrumented
    if _instrumented:
        return
    # Initialize OTel Tracing
    trace.set_tracer_provider(TracerProvider())
    trace.get_tracer_provider().add_span_processor(
        BatchSpanProcessor(ConsoleSpanExporter())
    )
    BotocoreInstrumentor().instrument()

    # Patch all supported libraries
    patch_all()
    _instrumented = True


cw = boto3.client("cloudwatch", region_name=os.getenv("AWS_REGION", "us-east-1"))


def publish_metric(name, value, unit="None"):
    try:
        cw.put_metric_data(
            Namespace="BlitzScale/Edge",
            MetricData=[{"MetricName": name, "Value": value, "Unit": unit}],
        )
    except Exception as e:
        logger.error(f"Metric error: {e}")


# --- Input Validation Schema ---
class GameStats(BaseModel):
    score: Optional[int] = 0
    yards: Optional[int] = 0
    tds: Optional[int] = 0
    # Fantasy-specific stats
    passing_yards: Optional[float] = 0
    passing_tds: Optional[int] = 0
    passing_ints: Optional[int] = 0
    rushing_yards: Optional[float] = 0
    rushing_tds: Optional[int] = 0
    receptions: Optional[int] = 0
    receiving_yards: Optional[float] = 0
    receiving_tds: Optional[int] = 0
    fumbles: Optional[int] = 0


class FantasyDelta(BaseModel):
    previous_points: float
    current_points: float
    points_delta: float
    breakdown_delta: Dict[str, float]
    significant_change: bool
    start_sit_signal: Optional[str] = None


class IngestEvent(BaseModel):
    game_id: str
    player_id: str
    player_name: Optional[str] = None
    timestamp: int
    stats: Dict[str, int]
    # Multi-tenant support
    league_id: Optional[str] = None
    user_id: Optional[str] = None
    # Fantasy context
    projected_points: Optional[float] = None
    scoring_format: Optional[str] = "ppr"  # ppr, half_ppr, standard

    @validator("timestamp")
    def validate_timestamp(cls, v):
        if v < 0:
            raise ValueError("Invalid timestamp")
        return v

    @validator("scoring_format")
    def validate_scoring_format(cls, v):
        if v not in ["ppr", "half_ppr", "standard"]:
            return "ppr"  # Default to PPR if invalid
        return v


# --- Optimized AWS Config ---
aws_config = Config(retries={"max_attempts": 3, "mode": "standard"})
dynamodb = boto3.resource(
    "dynamodb", region_name=os.getenv("AWS_REGION", "us-east-1"), config=aws_config
)
table = dynamodb.Table(os.getenv("STATE_TABLE_NAME", "blitz-game-state-versions"))

logger = logging.getLogger("DeltaProcessor")
logger.setLevel(logging.INFO)

REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379")
EDGE_WEBHOOK_URL = os.getenv("EDGE_WEBHOOK_URL")


def get_secret(secret_name):
    client = boto3.client(
        "secretsmanager", region_name=os.getenv("AWS_REGION", "us-east-1")
    )
    try:
        get_secret_value_response = client.get_secret_value(SecretId=secret_name)
        return get_secret_value_response["SecretString"]
    except Exception as e:
        logger.error(f"Failed to fetch secret {secret_name}: {e}")
        return os.getenv("WEBHOOK_SECRET_TOKEN")  # Fallback for local dev


WEBHOOK_SECRET_TOKEN = get_secret("blitz-edge-webhook-token")


async def get_redis():
    return await aioredis.from_url(REDIS_URL, decode_responses=True)


async def push_to_edge(deltas):
    """Pushes computed delta updates to the Edge network with exponential backoff."""
    if not deltas:
        return

    import random

    import aiohttp

    max_retries = 3
    base_delay = 0.1  # 100ms

    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {WEBHOOK_SECRET_TOKEN}",
    }

    async with aiohttp.ClientSession() as session:
        for attempt in range(max_retries):
            try:
                async with session.post(
                    EDGE_WEBHOOK_URL,
                    json={"events": deltas},
                    headers=headers,
                    timeout=2,
                ) as resp:
                    if resp.status == 200:
                        logger.info(f"Pushed {len(deltas)} updates to edge.")
                        return
                    elif resp.status in [429, 500, 502, 503, 504]:
                        delay = base_delay * (2**attempt) + random.uniform(0, 0.1)
                        logger.warning(
                            f"Edge push transient error {resp.status}. Retrying in {delay:.2f}s..."
                        )
                        await asyncio.sleep(delay)
                    else:
                        logger.error(f"Edge push fatal error {resp.status}")
                        break
            except Exception as e:
                logger.error(f"Network error (attempt {attempt + 1}): {e}")
                await asyncio.sleep(base_delay * (2**attempt))


async def compute_deltas_batched(records, redis):
    """
    Computes deltas for a batch of records using Redis pipelining.
    Includes fantasy points calculation for FantasyPros integration.
    Ensures state consistency via DynamoDB versioning.
    """
    deltas = []
    pipe = redis.pipeline()

    # 1. Batch GET current states
    keys = [f"state:{r['game_id']}:{r['player_id']}" for r in records]
    for key in keys:
        pipe.get(key)

    current_states_raw = await pipe.execute()

    # 2. Compare and build batch update
    pipe = redis.pipeline()
    for i, record in enumerate(records):
        game_id = record["game_id"]
        player_id = record["player_id"]
        player_name = record.get("player_name", "")
        new_stats = record.get("stats", {})
        league_id = record.get("league_id")
        user_id = record.get("user_id")
        projected_points = record.get("projected_points")
        scoring_format = record.get("scoring_format", "ppr")

        current_state_raw = current_states_raw[i]
        old_stats = (
            json.loads(current_state_raw).get("stats", {}) if current_state_raw else {}
        )

        # Calculate stat deltas
        stat_delta = {k: v for k, v in new_stats.items() if old_stats.get(k) != v}

        # Calculate fantasy points delta
        fantasy_delta = None
        if any(
            k in new_stats
            for k in ["passing_yards", "rushing_yards", "receptions", "receiving_yards"]
        ):
            try:
                fantasy_delta = calculate_fantasy_delta(
                    old_stats, new_stats, scoring_format
                )

                # Generate start/sit signal if there's a significant change
                if fantasy_delta["significant_change"] and projected_points:
                    signal = generate_start_sit_signal(fantasy_delta, projected_points)
                    fantasy_delta["start_sit_signal"] = signal

            except Exception as e:
                logger.warning(f"Fantasy calculation failed for {player_id}: {e}")

        if stat_delta or fantasy_delta or not current_state_raw:
            update = {
                "game_id": game_id,
                "player_id": player_id,
                "player_name": player_name,
                "timestamp": record.get("timestamp"),
                "stat_delta": stat_delta if stat_delta else new_stats,
                "fantasy_delta": fantasy_delta,
                "is_full": not current_state_raw,
                "league_id": league_id,
                "user_id": user_id,
                "scoring_format": scoring_format,
            }
            deltas.append(update)

            # Update Redis Cache with full record including fantasy calculation
            record_to_store = {
                **record,
                "fantasy_points": fantasy_delta["current_points"]
                if fantasy_delta
                else 0,
                "cached_at": record.get("timestamp"),
            }
            pipe.set(
                f"state:{game_id}:{player_id}", json.dumps(record_to_store), ex=3600
            )

            # Emit fantasy points metric if significant change
            if fantasy_delta and fantasy_delta["significant_change"]:
                publish_metric(
                    f"FantasyPointsDelta_{scoring_format}",
                    abs(fantasy_delta["points_delta"]),
                    "Count",
                )

    if deltas:
        await pipe.execute()

    return deltas


def lambda_handler(event, context):
    """Main entry point - wraps async loop."""
    setup_instrumentation()
    return asyncio.run(async_main(event))


async def async_main(event):
    records_to_process = []
    for record in event.get("Records", []):
        try:
            payload = base64.b64decode(record["kinesis"]["data"]).decode("utf-8")
            records_to_process.append(json.loads(payload))
        except Exception as e:
            logger.error(f"Decode error: {e}")

    if not records_to_process:
        return {"statusCode": 200}

    redis = await get_redis()
    try:
        with xray_recorder.in_segment("ComputeDeltas"):
            deltas = await compute_deltas_batched(records_to_process, redis)
            publish_metric("DeltasProduced", len(deltas), "Count")

        with xray_recorder.in_segment("PushToEdge"):
            await push_to_edge(deltas)
    finally:
        await redis.close()

    return {
        "statusCode": 200,
        "body": f"Processed {len(records_to_process)} records. Deltas: {len(deltas)}",
    }
