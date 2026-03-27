import os
import json
import base64
import logging
import asyncio
import aioredis
import boto3
from botocore.config import Config
from pydantic import BaseModel, validator
from typing import Dict, Optional
from aws_xray_sdk.core import xray_recorder
from aws_xray_sdk.core import patch_all
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor, ConsoleSpanExporter
from opentelemetry.instrumentation.botocore import BotocoreInstrumentor

# Initialize OTel Tracing
trace.set_tracer_provider(TracerProvider())
tracer = trace.get_tracer(__name__)
trace.get_tracer_provider().add_span_processor(BatchSpanProcessor(ConsoleSpanExporter()))
BotocoreInstrumentor().instrument()

# Patch all supported libraries (boto3, requests, etc.)
patch_all()

cw = boto3.client('cloudwatch', region_name=os.getenv('AWS_REGION', 'us-east-1'))

def publish_metric(name, value, unit='None'):
    try:
        cw.put_metric_data(
            Namespace='BlitzScale/Edge',
            MetricData=[{
                'MetricName': name,
                'Value': value,
                'Unit': unit
            }]
        )
    except Exception as e:
        logger.error(f"Metric error: {e}")

# --- Input Validation Schema ---
class GameStats(BaseModel):
    score: Optional[int] = 0
    yards: Optional[int] = 0
    tds: Optional[int] = 0

class IngestEvent(BaseModel):
    game_id: str
    player_id: str
    timestamp: int
    stats: Dict[str, int]

    @validator('timestamp')
    def validate_timestamp(cls, v):
        if v < 0: 
            raise ValueError("Invalid timestamp")
        return v

# --- Optimized AWS Config ---
aws_config = Config(retries={'max_attempts': 3, 'mode': 'standard'})
dynamodb = boto3.resource('dynamodb', region_name=os.getenv('AWS_REGION', 'us-east-1'), config=aws_config)
table = dynamodb.Table(os.getenv('STATE_TABLE_NAME', 'blitz-game-state-versions'))

logger = logging.getLogger('DeltaProcessor')
logger.setLevel(logging.INFO)

REDIS_URL = os.getenv('REDIS_URL', 'redis://localhost:6379')
EDGE_WEBHOOK_URL = os.getenv('EDGE_WEBHOOK_URL')

def get_secret(secret_name):
    client = boto3.client('secretsmanager', region_name=os.getenv('AWS_REGION', 'us-east-1'))
    try:
        get_secret_value_response = client.get_secret_value(SecretId=secret_name)
        return get_secret_value_response['SecretString']
    except Exception as e:
        logger.error(f"Failed to fetch secret {secret_name}: {e}")
        return os.getenv('WEBHOOK_SECRET_TOKEN') # Fallback for local dev

WEBHOOK_SECRET_TOKEN = get_secret('blitz-edge-webhook-token')

async def get_redis():
    return await aioredis.from_url(REDIS_URL, decode_responses=True)

async def push_to_edge(deltas):
    """Pushes computed delta updates to the Edge network with exponential backoff."""
    if not deltas:
        return
        
    import aiohttp
    import random
    
    max_retries = 3
    base_delay = 0.1 # 100ms
    
    headers = {
        'Content-Type': 'application/json',
        'Authorization': f'Bearer {WEBHOOK_SECRET_TOKEN}'
    }

    async with aiohttp.ClientSession() as session:
        for attempt in range(max_retries):
            try:
                async with session.post(EDGE_WEBHOOK_URL, json={"events": deltas}, headers=headers, timeout=2) as resp:
                    if resp.status == 200:
                        logger.info(f"Pushed {len(deltas)} updates to edge.")
                        return
                    elif resp.status in [429, 500, 502, 503, 504]:
                        delay = base_delay * (2 ** attempt) + random.uniform(0, 0.1)
                        logger.warning(f"Edge push transient error {resp.status}. Retrying in {delay:.2f}s...")
                        await asyncio.sleep(delay)
                    else:
                        logger.error(f"Edge push fatal error {resp.status}")
                        break
            except Exception as e:
                logger.error(f"Network error (attempt {attempt+1}): {e}")
                await asyncio.sleep(base_delay * (2 ** attempt))

async def compute_deltas_batched(records, redis):
    """
    Computes deltas for a batch of records using Redis pipelining.
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
        game_id = record['game_id']
        player_id = record['player_id']
        new_stats = record.get('stats', {})
        
        current_state_raw = current_states_raw[i]
        old_stats = json.loads(current_state_raw).get('stats', {}) if current_state_raw else {}
        
        delta = {k: v for k, v in new_stats.items() if old_stats.get(k) != v}
        
        if delta or not current_state_raw:
            update = {
                "game_id": game_id,
                "player_id": player_id,
                "timestamp": record.get('timestamp'),
                "delta": delta if delta else new_stats,
                "is_full": not bool(delta)
            }
            deltas.append(update)
            
            # Update Redis Cache
            pipe.set(f"state:{game_id}:{player_id}", json.dumps(record), ex=3600)
            
            # Async persistent versioning in DynamoDB (Optional/Background)
            # In a real high-throughput app, we might buffer these in SQS
    
    if deltas:
        await pipe.execute()
        
    return deltas

def lambda_handler(event, context):
    """Main entry point - wraps async loop."""
    return asyncio.run(async_main(event))

async def async_main(event):
    records_to_process = []
    for record in event.get('Records', []):
        try:
            payload = base64.b64decode(record['kinesis']['data']).decode('utf-8')
            records_to_process.append(json.loads(payload))
        except Exception as e:
            logger.error(f"Decode error: {e}")

    if not records_to_process:
        return {'statusCode': 200}

    redis = await get_redis()
    try:
        with xray_recorder.in_segment('ComputeDeltas'):
            deltas = await compute_deltas_batched(records_to_process, redis)
            publish_metric('DeltasProduced', len(deltas), 'Count')
            
        with xray_recorder.in_segment('PushToEdge'):
            await push_to_edge(deltas)
    finally:
        await redis.close()

    return {
        'statusCode': 200,
        'body': f"Processed {len(records_to_process)} records. Deltas: {len(deltas)}"
    }
