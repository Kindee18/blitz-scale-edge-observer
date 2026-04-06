import sys
import json
import base64
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

# Mock dependencies before import
sys.modules.setdefault("aioredis", MagicMock())
sys.modules.setdefault("aws_xray_sdk", MagicMock())
sys.modules.setdefault("aws_xray_sdk.core", MagicMock())
sys.modules.setdefault("opentelemetry", MagicMock())
sys.modules.setdefault("opentelemetry.trace", MagicMock())
sys.modules.setdefault("opentelemetry.sdk", MagicMock())
sys.modules.setdefault("opentelemetry.sdk.trace", MagicMock())
sys.modules.setdefault("opentelemetry.sdk.trace.export", MagicMock())
sys.modules.setdefault("opentelemetry.instrumentation.botocore", MagicMock())

from streaming.delta_processor_lambda import async_main  # noqa: E402


def _make_kinesis_record(game_id, player_id, timestamp, stats):
    payload = json.dumps({"game_id": game_id, "player_id": player_id,
                          "timestamp": timestamp, "stats": stats})
    return {"kinesis": {"data": base64.b64encode(payload.encode()).decode()}}


def test_pipeline_integration_flow():
    """Verifies Kinesis -> Delta Processor -> Edge webhook push produces correct deltas."""

    records = [
        _make_kinesis_record("NFL_101", "P1", 100, {"score": 7, "yards": 150}),
        _make_kinesis_record("NFL_101", "P1", 200, {"score": 7, "yards": 165}),  # only yards changed
    ]
    event = {"Records": records}

    mock_redis = MagicMock()
    mock_pipe = MagicMock()
    mock_redis.pipeline.return_value = mock_pipe
    mock_pipe.get = MagicMock()
    mock_pipe.set = MagicMock()
    mock_pipe.execute = AsyncMock(side_effect=[
        [None, json.dumps({"stats": {"score": 7, "yards": 150}})],  # MGET
        ["OK", "OK"],  # MSET
    ])
    mock_redis.set = AsyncMock(return_value=True)   # dedupe check
    mock_redis.aclose = AsyncMock()                 # cleanup

    mock_resp = MagicMock()
    mock_resp.status = 200

    with patch("streaming.delta_processor_lambda.get_redis", new=AsyncMock(return_value=mock_redis)), \
         patch("streaming.delta_processor_lambda.get_secret", return_value="test-token"), \
         patch("streaming.delta_processor_lambda.EDGE_WEBHOOK_URL", "https://mock-edge.example.com/webhook"), \
         patch("aiohttp.ClientSession.post") as mock_post:

        mock_post.return_value.__aenter__.return_value = mock_resp
        result = asyncio.run(async_main(event))

    body = json.loads(result["body"])
    assert result["statusCode"] == 200
    assert body["processed"] == 2
    assert body["deltas"] >= 1  # at least the full-sync delta
    assert body["malformed"] == 0
