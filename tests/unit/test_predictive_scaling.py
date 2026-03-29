import sys
from unittest.mock import MagicMock

# Mock kubernetes before it is imported
sys.modules["kubernetes"] = MagicMock()
sys.modules["kubernetes.client"] = MagicMock()
sys.modules["kubernetes.config"] = MagicMock()

from datetime import datetime, timedelta, timezone  # noqa: E402
from scaling.predictive_scaling import is_spike_imminent  # noqa: E402


def test_is_spike_imminent_true():
    now = datetime.now(timezone.utc)
    kickoff = now + timedelta(minutes=20)
    schedule = [{"game_id": "G1", "kickoff_time": kickoff.isoformat()}]

    imminent, games = is_spike_imminent(schedule, lead_time_minutes=30)
    assert imminent is True
    assert len(games) == 1


def test_is_spike_imminent_false_future():
    now = datetime.now(timezone.utc)
    kickoff = now + timedelta(minutes=60)
    schedule = [{"game_id": "G1", "kickoff_time": kickoff.isoformat()}]

    imminent, games = is_spike_imminent(schedule, lead_time_minutes=30)
    assert imminent is False
    assert len(games) == 0


def test_is_spike_imminent_false_past():
    now = datetime.now(timezone.utc)
    kickoff = now - timedelta(minutes=10)
    schedule = [{"game_id": "G1", "kickoff_time": kickoff.isoformat()}]

    imminent, games = is_spike_imminent(schedule, lead_time_minutes=30)
    assert imminent is False
    assert len(games) == 0
