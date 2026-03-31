import pytest
import json
import sys
from unittest.mock import AsyncMock, MagicMock

# Mock problematic libraries before they are imported by the code under test
mock_redis = MagicMock()
mock_redis.RedisError = Exception
sys.modules["aioredis"] = mock_redis
sys.modules["aws_xray_sdk"] = MagicMock()
sys.modules["aws_xray_sdk.core"] = MagicMock()
sys.modules["opentelemetry"] = MagicMock()
sys.modules["opentelemetry.trace"] = MagicMock()
sys.modules["opentelemetry.sdk.trace"] = MagicMock()
sys.modules["opentelemetry.sdk.trace.export"] = MagicMock()
sys.modules["opentelemetry.instrumentation.botocore"] = MagicMock()

from streaming.delta_processor_lambda import compute_deltas_batched  # noqa: E402


@pytest.mark.asyncio
async def test_compute_deltas_batched_no_previous_state():
    """Test delta calculation when no state exists in Redis (Full sync expected)."""
    mock_redis = MagicMock()
    mock_pipe = MagicMock()
    mock_redis.pipeline.return_value = mock_pipe
    mock_pipe.execute = AsyncMock(
        side_effect=[
            [None, None],  # Initial MGET results
            ["OK", "OK"],  # MSET results
        ]
    )

    records = [
        {"game_id": "G1", "player_id": "P1", "stats": {"score": 10}, "timestamp": 123},
        {"game_id": "G1", "player_id": "P2", "stats": {"score": 20}, "timestamp": 124},
    ]

    deltas = await compute_deltas_batched(records, mock_redis)

    assert len(deltas) == 2
    assert deltas[0]["stat_delta"] == {"score": 10}
    assert deltas[0]["is_full"] is True


@pytest.mark.asyncio
async def test_compute_deltas_batched_with_partial_change():
    """Test delta calculation when stats have partially changed."""
    mock_redis = MagicMock()
    mock_pipe = MagicMock()
    mock_redis.pipeline.return_value = mock_pipe
    old_state = json.dumps({"stats": {"score": 10, "yards": 50}})

    mock_pipe.execute = AsyncMock(
        side_effect=[
            [old_state],  # Initial MGET
            ["OK"],  # MSET
        ]
    )

    records = [
        {
            "game_id": "G1",
            "player_id": "P1",
            "stats": {"score": 10, "yards": 60},
            "timestamp": 125,
        }
    ]

    deltas = await compute_deltas_batched(records, mock_redis)

    assert len(deltas) == 1
    assert deltas[0]["stat_delta"] == {"yards": 60}
    assert deltas[0]["is_full"] is False


@pytest.mark.asyncio
async def test_compute_deltas_batched_no_change():
    """Test delta calculation when no stats have changed."""
    mock_redis = MagicMock()
    mock_pipe = MagicMock()
    mock_redis.pipeline.return_value = mock_pipe
    old_state = json.dumps({"stats": {"score": 10}})

    mock_pipe.execute = AsyncMock(
        side_effect=[
            [old_state],  # Initial MGET
            [],  # No MSET expected
        ]
    )

    records = [
        {"game_id": "G1", "player_id": "P1", "stats": {"score": 10}, "timestamp": 126}
    ]

    deltas = await compute_deltas_batched(records, mock_redis)
    assert len(deltas) == 0
