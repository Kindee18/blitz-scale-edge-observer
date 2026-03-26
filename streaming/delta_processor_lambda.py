import os
import json
import base64
import logging
import urllib.request
import urllib.error

# Mock Redis since we're providing the code architecture
# In a real environment, we'd use redis-py
class MockRedis:
    def __init__(self):
        self.store = {}
    
    def get(self, key):
        return self.store.get(key)
    
    def set(self, key, value):
        self.store[key] = value

try:
    import redis
    redis_client = redis.Redis.from_url(os.getenv('REDIS_URL', 'redis://localhost:6379'))
except ImportError:
    redis_client = MockRedis()

logger = logging.getLogger('DeltaProcessor')
logger.setLevel(logging.INFO)

EDGE_WEBHOOK_URL = os.getenv('EDGE_WEBHOOK_URL', 'https://api.edge.cloudflare.workers/webhook/update')
WEBHOOK_SECRET_TOKEN = os.getenv('WEBHOOK_SECRET_TOKEN', 'secret')

def push_to_edge(deltas):
    """Pushes the computed delta updates to the Edge network (Cloudflare Worker)."""
    if not deltas:
        return
        
    payload = json.dumps({"events": deltas}).encode('utf-8')
    req = urllib.request.Request(EDGE_WEBHOOK_URL, data=payload, method='POST')
    req.add_header('Content-Type', 'application/json')
    req.add_header('Authorization', f'Bearer {WEBHOOK_SECRET_TOKEN}')
    
    try:
        response = urllib.request.urlopen(req, timeout=3)
        logger.info(f"Successfully pushed {len(deltas)} updates to edge. Response: {response.status}")
    except urllib.error.URLError as e:
        logger.error(f"Failed to push to edge: {e}")

def compute_delta(event):
    """
    Compares the incoming event state against the cached state in Redis.
    Returns the delta payload (e.g. only changed stats like score), or None if no change.
    """
    game_id = event.get('game_id')
    player_id = event.get('player_id')
    
    cache_key = f"state:{game_id}:{player_id}"
    current_state_raw = redis_client.get(cache_key)
    
    if current_state_raw:
        current_state = json.loads(current_state_raw)
        # Assuming event contains full stats for the player/game at a tick
        # We only want to push what has changed
        delta = {}
        new_stats = event.get('stats', {})
        old_stats = current_state.get('stats', {})
        
        for key, val in new_stats.items():
            if old_stats.get(key) != val:
                delta[key] = val
                
        if not delta:
            return None # No meaningful change
            
        update = {
            "game_id": game_id,
            "player_id": player_id,
            "timestamp": event.get('timestamp'),
            "delta": delta
        }
    else:
        # First time seeing this state, push full stats as delta
        update = event
        
    # Update cache
    redis_client.set(cache_key, json.dumps(event))
    return update

def lambda_handler(event, context):
    """
    AWS Lambda entry point triggered by Kinesis batches
    """
    records = event.get('Records', [])
    deltas_to_push = []
    
    logger.info(f"Processing {len(records)} records from Kinesis")
    
    for record in records:
        try:
            # Kinesis data is base64 encoded
            payload = base64.b64decode(record['kinesis']['data']).decode('utf-8')
            parsed_event = json.loads(payload)
            
            delta = compute_delta(parsed_event)
            if delta:
                deltas_to_push.append(delta)
        except Exception as e:
            logger.error(f"Error processing record: {e}")
            
    # Push aggregated deltas to the Edge network
    push_to_edge(deltas_to_push)
    
    return {
        'statusCode': 200,
        'body': f'Processed {len(records)} records. Pushed {len(deltas_to_push)} deltas.'
    }
