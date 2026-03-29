import asyncio
import json
import logging
import time

try:
    import websockets
except ImportError:
    logging.warning("websockets module not installed. Run: pip install websockets")

logger = logging.getLogger("ClientSim")
logger.setLevel(logging.INFO)
logging.basicConfig(level=logging.INFO)

EDGE_WS_URL = "wss://api.blitz-obs.com/realtime"


async def client_session(client_id):
    """Simulates a single mobile app client connected to the edge via WebSockets"""
    try:
        async with websockets.connect(
            f"{EDGE_WS_URL}?client_id={client_id}"
        ) as websocket:
            logger.info(f"Client {client_id} connected")

            # Subscribe to specific games
            subscribe_msg = {"action": "subscribe", "games": ["NFL_101", "NFL_102"]}
            await websocket.send(json.dumps(subscribe_msg))

            while True:
                # Wait for push messages (deltas)
                message = await websocket.recv()
                data = json.loads(message)

                # Measure latency (assuming the server includes a timestamp)
                server_ts = data.get("timestamp")
                if server_ts:
                    latency = (time.time() * 1000) - int(server_ts)
                    logger.info(
                        f"Client {client_id} | Update received | Latency: {latency:.1f}ms | Payload: {data['delta']}"
                    )
                else:
                    logger.info(f"Client {client_id} | Message received: {data}")

    except Exception as e:
        logger.error(f"Client {client_id} disconnected: {e}")


async def main():
    logger.info("Starting Real-Time Edge Data Client Simulation...")
    # Simulate 5 concurrent clients for local testing
    # In a real load test, this would be thousands
    tasks = [client_session(i) for i in range(5)]
    await asyncio.gather(*tasks)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Simulation stopped.")
