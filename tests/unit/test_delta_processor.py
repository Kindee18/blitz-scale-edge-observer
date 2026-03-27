import pytest
import json
from unittest.mock import AsyncMock
from streaming.delta_processor_lambda import compute_deltas_batched

@pytest.mark.asyncio
async def test_compute_deltas_batched_no_previous_state():
    """Test delta calculation when no state exists in Redis (Full sync expected)."""
    mock_redis = AsyncMock()
    mock_redis.pipeline.return_value.execute.side_effect = [
        [None, None], # Initial MGET results
        ["OK", "OK"]  # MSET results
    ]
    
    records = [
        {"game_id": "G1", "player_id": "P1", "stats": {"score": 10}, "timestamp": 123},
        {"game_id": "G1", "player_id": "P2", "stats": {"score": 20}, "timestamp": 124}
    ]
    
    deltas = await compute_deltas_batched(records, mock_redis)
    
    assert len(deltas) == 2
    assert deltas[0]["delta"] == {"score": 10}
    assert deltas[0]["is_full"] is True

@pytest.mark.asyncio
async def test_compute_deltas_batched_with_partial_change():
    """Test delta calculation when stats have partially changed."""
    mock_redis = AsyncMock()
    old_state = json.dumps({"stats": {"score": 10, "yards": 50}})
    
    mock_redis.pipeline.return_value.execute.side_effect = [
        [old_state], # Initial MGET
        ["OK"]       # MSET
    ]
    
    records = [
        {"game_id": "G1", "player_id": "P1", "stats": {"score": 10, "yards": 60}, "timestamp": 125}
    ]
    
    deltas = await compute_deltas_batched(records, mock_redis)
    
    assert len(deltas) == 1
    assert deltas[0]["delta"] == {"yards": 60}
    assert deltas[0]["is_full"] is False

@pytest.mark.asyncio
async def test_compute_deltas_batched_no_change():
    """Test delta calculation when no stats have changed."""
    mock_redis = AsyncMock()
    old_state = json.dumps({"stats": {"score": 10}})
    
    mock_redis.pipeline.return_value.execute.side_effect = [
        [old_state], # Initial MGET
        []           # No MSET expected
    ]
    
    records = [
        {"game_id": "G1", "player_id": "P1", "stats": {"score": 10}, "timestamp": 126}
    ]
    
    deltas = await compute_deltas_batched(records, mock_redis)
    assert len(deltas) == 0
