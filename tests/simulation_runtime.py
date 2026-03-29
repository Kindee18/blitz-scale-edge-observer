import sys
import json
import base64
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch


# --- 1. Mock Infrastructure ---
class MockRedisClient(AsyncMock):
    def pipeline(self):
        return self


class MockRedisModule:
    @staticmethod
    async def from_url(*args, **kwargs):
        return MockRedisClient()


class MockOTel:
    trace = MagicMock()

    class TracerProvider:
        def get_tracer(self, *args):
            return MagicMock()

        def add_span_processor(self, *args):
            pass

    class BatchSpanProcessor:
        def __init__(self, *args, **kwargs):
            pass

    class ConsoleSpanExporter:
        def __init__(self, *args, **kwargs):
            pass


# Patch and Load
sys.modules["aioredis"] = MockRedisModule
sys.modules["opentelemetry"] = MockOTel
sys.modules["opentelemetry.trace"] = MockOTel.trace
sys.modules["opentelemetry.sdk"] = MagicMock()
sys.modules["opentelemetry.sdk.trace"] = MockOTel
sys.modules["opentelemetry.sdk.trace.export"] = MockOTel
sys.modules["opentelemetry.instrumentation.botocore"] = MagicMock()
sys.modules["aws_xray_sdk.core"] = MagicMock()
sys.modules["aws_xray_sdk.core.patch_all"] = MagicMock()

from streaming.delta_processor_lambda import async_main  # noqa: E402


async def run_simulation():
    print("🚀 Starting Blitz-Scale Edge Observer Simulation (Final Batch Fix)...")

    # 2. Simulation Records (2 events)
    records = [
        {
            "kinesis": {
                "data": base64.b64encode(
                    json.dumps(
                        {
                            "game_id": "NFL_101",
                            "player_id": "P1",
                            "timestamp": 100,
                            "stats": {"score": 7, "yards": 150},
                        }
                    ).encode("utf-8")
                ).decode("utf-8")
            }
        },
        {
            "kinesis": {
                "data": base64.b64encode(
                    json.dumps(
                        {
                            "game_id": "NFL_101",
                            "player_id": "P1",
                            "timestamp": 200,
                            "stats": {"score": 7, "yards": 165},  # Delta: +15 yards
                        }
                    ).encode("utf-8")
                ).decode("utf-8")
            }
        },
    ]

    event = {"Records": records}

    with (
        patch("streaming.delta_processor_lambda.get_redis") as mock_redis_getter,
        patch(
            "streaming.delta_processor_lambda.get_secret", return_value="secure-token"
        ),
        patch("aiohttp.ClientSession.post") as mock_post,
    ):
        # Redis Batch Simulation
        mock_redis = MockRedisClient()
        mock_redis.execute.side_effect = [
            [None, json.dumps({"stats": {"score": 7, "yards": 150}})],  # MGET for both
            ["OK", "OK"],  # MSET for both
        ]
        mock_redis_getter.return_value = mock_redis

        mock_resp = MagicMock()
        mock_resp.status = 200
        mock_post.return_value.__aenter__.return_value = mock_resp

        print("📥 Processing Kinesis batch...")
        result = await async_main(event)

        # 4. Success Validations
        print(f"📊 {result['body']}")

        # Verify Webhook Data
        call_args = mock_post.call_args_list
        # The Lambda calls push_to_edge once per total batch if there are deltas
        posted_events = call_args[0][1]["json"]["events"]
        print(f"🎯 Total Deltas Emitted: {len(posted_events)}")

        print(f"✅ Full Sync Event: {posted_events[0]['delta']}")
        print(f"✅ Partial Delta Event: {posted_events[1]['delta']}")

        assert posted_events[1]["delta"] == {"yards": 165}

    print("🏆 Simulation Complete: 100% Success Rate")


if __name__ == "__main__":
    asyncio.run(run_simulation())
