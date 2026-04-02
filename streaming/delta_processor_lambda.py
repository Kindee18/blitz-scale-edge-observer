import asyncio
import base64
import json
import logging
import os
import random
import sys
import time
import urllib.request
from typing import Dict, Optional

import redis.asyncio as redis_async
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
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from fantasy_scoring import calculate_fantasy_delta, generate_start_sit_signal
from monitoring.custom_metrics import DeltaProcessorMetrics

_instrumented = False


logger = logging.getLogger("DeltaProcessor")
logger.setLevel(logging.INFO)


def setup_instrumentation():
    global _instrumented
    if _instrumented:
        return

    trace.set_tracer_provider(TracerProvider())
    trace.get_tracer_provider().add_span_processor(
        BatchSpanProcessor(ConsoleSpanExporter())
    )
    BotocoreInstrumentor().instrument()
    patch_all()
    _instrumented = True


METRICS = DeltaProcessorMetrics(region=os.getenv("AWS_REGION", "us-east-1"))


def publish_metric(name, value, unit="None"):
    try:
        METRICS.emit(name, value, unit)
    except Exception as exc:
        logger.error(f"Metric error: {exc}")


# --- Input Validation Schema ---
class IngestEvent(BaseModel):
    game_id: str
    player_id: str
    player_name: Optional[str] = None
    timestamp: int
    stats: Dict[str, float]
    # Multi-tenant support
    league_id: Optional[str] = None
    user_id: Optional[str] = None
    # Fantasy context
    projected_points: Optional[float] = None
    scoring_format: Optional[str] = "ppr"  # ppr, half_ppr, standard
    sport: Optional[str] = "nfl"

    @validator("timestamp")
    def validate_timestamp(cls, value):
        if value < 0:
            raise ValueError("Invalid timestamp")
        return value

    @validator("scoring_format")
    def validate_scoring_format(cls, value):
        if value not in ["ppr", "half_ppr", "standard"]:
            return "ppr"
        return value

    @validator("sport")
    def validate_sport(cls, value):
        supported = ["nfl", "nba", "mlb", "nhl"]
        if value not in supported:
            return "nfl"
        return value


# --- Optimized AWS Config ---
aws_config = Config(retries={"max_attempts": 3, "mode": "standard"})
dynamodb = boto3.resource(
    "dynamodb", region_name=os.getenv("AWS_REGION", "us-east-1"), config=aws_config
)
table = dynamodb.Table(os.getenv("STATE_TABLE_NAME", "blitz-game-state-versions"))

REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379")
EDGE_WEBHOOK_URL = os.getenv("EDGE_WEBHOOK_URL")
DELTA_PROCESSOR_DLQ_URL = os.getenv("DELTA_PROCESSOR_DLQ_URL")
WEBHOOK_SECRET_NAME = os.getenv("WEBHOOK_SECRET_NAME", "blitz-edge-webhook-token")

EDGE_PUSH_BATCH_SIZE = int(os.getenv("EDGE_PUSH_BATCH_SIZE", "50"))
CIRCUIT_FAILURE_THRESHOLD = int(os.getenv("EDGE_CIRCUIT_FAILURE_THRESHOLD", "3"))
CIRCUIT_COOLDOWN_SECONDS = int(os.getenv("EDGE_CIRCUIT_COOLDOWN_SECONDS", "30"))
EVENT_DEDUPE_TTL_SECONDS = int(os.getenv("EVENT_DEDUPE_TTL_SECONDS", "300"))
PROCESSING_CHUNK_SIZE = int(os.getenv("DELTA_PROCESSOR_CHUNK_SIZE", "200"))
ALERTS_SNS_TOPIC_ARN = os.getenv("ALERTS_SNS_TOPIC_ARN")
PAGERDUTY_WEBHOOK_URL = os.getenv("PAGERDUTY_WEBHOOK_URL")

_CIRCUIT_STATE = {
    "consecutive_failures": 0,
    "open_until": 0,
}


def get_secret(secret_name):
    client = boto3.client(
        "secretsmanager", region_name=os.getenv("AWS_REGION", "us-east-1")
    )
    try:
        get_secret_value_response = client.get_secret_value(SecretId=secret_name)
        return get_secret_value_response["SecretString"]
    except Exception as exc:
        logger.error(f"Failed to fetch secret {secret_name}: {exc}")
        return os.getenv("WEBHOOK_SECRET_TOKEN")


WEBHOOK_SECRET_TOKEN = get_secret(WEBHOOK_SECRET_NAME)


def send_to_dlq(payload, reason):
    if not DELTA_PROCESSOR_DLQ_URL:
        return

    try:
        sqs = boto3.client("sqs", region_name=os.getenv("AWS_REGION", "us-east-1"))
        sqs.send_message(
            QueueUrl=DELTA_PROCESSOR_DLQ_URL,
            MessageBody=json.dumps(
                {
                    "reason": reason,
                    "payload": payload,
                    "failed_at": int(time.time() * 1000),
                }
            ),
        )
        publish_metric("DLQMessagesSent", 1, "Count")
    except Exception as exc:
        logger.error(f"Failed to push message to DLQ: {exc}")


def send_operational_alert(title, details):
    payload = {
        "service": "delta_processor",
        "title": title,
        "details": details,
        "timestamp": int(time.time() * 1000),
    }

    if ALERTS_SNS_TOPIC_ARN:
        try:
            sns = boto3.client("sns", region_name=os.getenv("AWS_REGION", "us-east-1"))
            sns.publish(
                TopicArn=ALERTS_SNS_TOPIC_ARN,
                Subject=title[:100],
                Message=json.dumps(payload),
            )
        except Exception as exc:
            logger.error(f"Failed to publish SNS alert: {exc}")

    if PAGERDUTY_WEBHOOK_URL:
        try:
            request = urllib.request.Request(
                PAGERDUTY_WEBHOOK_URL,
                data=json.dumps(payload).encode("utf-8"),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(request, timeout=2):
                pass
        except Exception as exc:
            logger.error(f"Failed to publish PagerDuty alert: {exc}")


async def get_redis():
    return redis_async.from_url(REDIS_URL, decode_responses=True)


async def is_duplicate_event(redis, dedupe_key):
    if not redis:
        return False
    try:
        stored = await redis.set(
            f"dedupe:{dedupe_key}",
            "1",
            ex=EVENT_DEDUPE_TTL_SECONDS,
            nx=True,
        )
        return not bool(stored)
    except Exception as exc:
        logger.warning(f"Dedupe check failed for {dedupe_key}: {exc}")
        return False


def _circuit_is_open():
    return time.time() < _CIRCUIT_STATE["open_until"]


def _record_edge_push_result(success):
    if success:
        _CIRCUIT_STATE["consecutive_failures"] = 0
        _CIRCUIT_STATE["open_until"] = 0
        return

    _CIRCUIT_STATE["consecutive_failures"] += 1
    if _CIRCUIT_STATE["consecutive_failures"] >= CIRCUIT_FAILURE_THRESHOLD:
        _CIRCUIT_STATE["open_until"] = time.time() + CIRCUIT_COOLDOWN_SECONDS
        publish_metric("EdgeCircuitOpen", 1, "Count")
        send_operational_alert(
            "DeltaProcessor edge circuit opened",
            {
                "threshold": CIRCUIT_FAILURE_THRESHOLD,
                "cooldown_seconds": CIRCUIT_COOLDOWN_SECONDS,
            },
        )


async def _push_batch(session, deltas, headers):
    max_retries = 3
    base_delay = 0.1

    for attempt in range(max_retries):
        try:
            async with session.post(
                EDGE_WEBHOOK_URL,
                json={"events": deltas},
                headers=headers,
                timeout=2,
            ) as resp:
                if resp.status == 200:
                    return True
                if resp.status in [429, 500, 502, 503, 504]:
                    delay = base_delay * (2**attempt) + random.uniform(0, 0.1)
                    logger.warning(
                        f"Edge push transient error {resp.status}. Retrying in {delay:.2f}s..."
                    )
                    await asyncio.sleep(delay)
                else:
                    logger.error(f"Edge push fatal error {resp.status}")
                    return False
        except Exception as exc:
            logger.error(f"Network error (attempt {attempt + 1}): {exc}")
            await asyncio.sleep(base_delay * (2**attempt))

    return False


async def push_to_edge(deltas):
    """Pushes computed delta updates to the edge network with retries and circuit breaker."""
    if not deltas:
        return True

    if _circuit_is_open():
        logger.warning(
            "Edge circuit breaker is open. Skipping push to protect downstream."
        )
        publish_metric("EdgePushSkippedCircuitOpen", len(deltas), "Count")
        return False

    if not EDGE_WEBHOOK_URL or not WEBHOOK_SECRET_TOKEN:
        logger.error("EDGE_WEBHOOK_URL or WEBHOOK_SECRET_TOKEN missing")
        publish_metric("EdgePushConfigError", 1, "Count")
        return False

    import aiohttp

    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {WEBHOOK_SECRET_TOKEN}",
    }

    all_success = True
    async with aiohttp.ClientSession() as session:
        for i in range(0, len(deltas), EDGE_PUSH_BATCH_SIZE):
            chunk = deltas[i : i + EDGE_PUSH_BATCH_SIZE]
            ok = await _push_batch(session, chunk, headers)
            all_success = all_success and ok
            if not ok:
                send_to_dlq(chunk, "edge_push_failed")

    _record_edge_push_result(all_success)
    if all_success:
        logger.info(f"Pushed {len(deltas)} updates to edge.")
    return all_success


def _build_fallback_delta(record, old_stats):
    projected_points = record.get("projected_points")
    if projected_points is None:
        return None

    try:
        previous_points = float(
            old_stats.get("fantasy_points", 0) if isinstance(old_stats, dict) else 0
        )
        current_points = float(projected_points)
    except Exception:
        return None

    points_delta = round(current_points - previous_points, 2)
    fallback = {
        "previous_points": previous_points,
        "current_points": current_points,
        "points_delta": points_delta,
        "breakdown_delta": {},
        "significant_change": abs(points_delta) >= 0.5,
        "start_sit_signal": generate_start_sit_signal(
            {
                "current_points": current_points,
                "points_delta": points_delta,
                "significant_change": abs(points_delta) >= 0.5,
            },
            current_points,
        ),
        "fallback_projection": True,
    }
    return fallback


async def compute_deltas_batched(records, redis):
    """Compute deltas for a batch of records using Redis pipelining."""
    deltas = []
    pipe = redis.pipeline()

    keys = [f"state:{r['game_id']}:{r['player_id']}" for r in records]
    for key in keys:
        pipe.get(key)

    current_states_raw = await pipe.execute()

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
        sport = record.get("sport", "nfl")

        current_state_raw = current_states_raw[i]
        old_record = json.loads(current_state_raw) if current_state_raw else {}
        old_stats = old_record.get("stats", {}) if isinstance(old_record, dict) else {}

        stat_delta = {k: v for k, v in new_stats.items() if old_stats.get(k) != v}

        fantasy_delta = None
        if new_stats:
            try:
                fantasy_delta = calculate_fantasy_delta(
                    old_stats,
                    new_stats,
                    scoring_format,
                    sport=sport,
                )
                if (
                    fantasy_delta.get("significant_change")
                    and projected_points is not None
                ):
                    signal = generate_start_sit_signal(fantasy_delta, projected_points)
                    fantasy_delta["start_sit_signal"] = signal
            except Exception as exc:
                logger.warning(f"Fantasy calculation failed for {player_id}: {exc}")
        else:
            fantasy_delta = _build_fallback_delta(record, old_record)

        has_fantasy_change = bool(
            fantasy_delta
            and (
                fantasy_delta.get("significant_change")
                or fantasy_delta.get("fallback_projection")
            )
        )

        if stat_delta or has_fantasy_change or not current_state_raw:
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
                "sport": sport,
            }
            deltas.append(update)

            record_to_store = {
                **record,
                "fantasy_points": fantasy_delta.get("current_points", 0)
                if fantasy_delta
                else 0,
                "cached_at": record.get("timestamp"),
            }
            pipe.set(
                f"state:{game_id}:{player_id}", json.dumps(record_to_store), ex=3600
            )

            if fantasy_delta and fantasy_delta.get("significant_change"):
                publish_metric(
                    f"FantasyPointsDelta_{scoring_format}_{sport}",
                    abs(fantasy_delta.get("points_delta", 0)),
                    "Count",
                )

    if deltas:
        await pipe.execute()

    return deltas


def _parse_kinesis_record(raw_record):
    payload = base64.b64decode(raw_record["kinesis"]["data"]).decode("utf-8")
    return json.loads(payload)


def _event_dedupe_key(event):
    event_id = event.get("event_id")
    if event_id:
        return f"event:{event_id}"
    return f"{event.get('game_id')}:{event.get('player_id')}:{event.get('timestamp')}"


def lambda_handler(event, context):
    """Main entry point - wraps async loop."""
    setup_instrumentation()
    return asyncio.run(async_main(event))


async def async_main(event):
    records_to_process = []
    malformed_count = 0
    duplicate_count = 0
    seen = set()
    redis = None

    try:
        redis = await get_redis()
    except Exception as exc:
        logger.warning(f"Redis unavailable for dedupe at startup: {exc}")
        redis = None

    for record in event.get("Records", []):
        try:
            parsed = _parse_kinesis_record(record)
            validated = IngestEvent(**parsed).dict()
            dedupe_key = _event_dedupe_key(validated)
            if dedupe_key in seen:
                duplicate_count += 1
                publish_metric("DuplicateEventsDropped", 1, "Count")
                continue
            if await is_duplicate_event(redis, dedupe_key):
                duplicate_count += 1
                publish_metric("DuplicateEventsDropped", 1, "Count")
                continue
            seen.add(dedupe_key)
            records_to_process.append(validated)
        except Exception as exc:
            malformed_count += 1
            logger.error(f"Decode/validation error: {exc}")
            send_to_dlq(record, "decode_or_validation_error")
            publish_metric("MalformedRecords", 1, "Count")

    if not records_to_process:
        return {
            "statusCode": 200,
            "body": json.dumps(
                {
                    "processed": 0,
                    "malformed": malformed_count,
                    "duplicates": duplicate_count,
                }
            ),
        }

    if redis is None:
        send_operational_alert(
            "DeltaProcessor redis unavailable",
            {
                "processed_candidates": len(records_to_process),
                "message": "Redis is required for stateful delta computation",
            },
        )
        return {
            "statusCode": 503,
            "body": json.dumps(
                {
                    "processed": 0,
                    "deltas": 0,
                    "malformed": malformed_count,
                    "duplicates": duplicate_count,
                    "error": "redis_unavailable",
                }
            ),
        }

    try:
        total_deltas = 0
        push_failure_batches = 0

        for i in range(0, len(records_to_process), PROCESSING_CHUNK_SIZE):
            chunk = records_to_process[i : i + PROCESSING_CHUNK_SIZE]

            with xray_recorder.in_segment("ComputeDeltas"):
                deltas = await compute_deltas_batched(chunk, redis)
                total_deltas += len(deltas)
                publish_metric("DeltasProduced", len(deltas), "Count")

            with xray_recorder.in_segment("PushToEdge"):
                success = await push_to_edge(deltas)
                if not success:
                    push_failure_batches += 1
                    publish_metric("EdgePushFailureBatches", 1, "Count")

        if malformed_count > 0:
            send_operational_alert(
                "DeltaProcessor malformed records detected",
                {"malformed": malformed_count, "duplicates": duplicate_count},
            )

        return {
            "statusCode": 200,
            "body": json.dumps(
                {
                    "processed": len(records_to_process),
                    "deltas": total_deltas,
                    "malformed": malformed_count,
                    "duplicates": duplicate_count,
                    "push_failure_batches": push_failure_batches,
                }
            ),
        }
    except Exception as exc:
        logger.error(f"Delta processor execution failed: {exc}")
        send_to_dlq(records_to_process, "processor_runtime_error")
        publish_metric("DeltaProcessorUnhandledError", 1, "Count")
        return {"statusCode": 500, "body": str(exc)}
    finally:
        if redis:
            await redis.aclose()
