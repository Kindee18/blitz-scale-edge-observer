import asyncio
import random
import logging
from streaming.client_sim import client_session

logger = logging.getLogger('ChaosClient')
logger.setLevel(logging.INFO)

async def chaos_loop():
    """Simulates network jitter and client churn to test edge resilience"""
    while True:
        # Randomly spawn or kill client sessions
        client_id = f"chaos_{random.randint(100, 999)}"
        action = random.choice(["connect", "wait"])
        
        if action == "connect":
            logger.info(f"Chaos Generator: Spawning {client_id}")
            asyncio.create_task(client_session(client_id))
        
        # Jitter
        await asyncio.sleep(random.uniform(0.5, 5))

if __name__ == "__main__":
    try:
        asyncio.run(chaos_loop())
    except KeyboardInterrupt:
        logger.info("Chaos simulation stopped.")
