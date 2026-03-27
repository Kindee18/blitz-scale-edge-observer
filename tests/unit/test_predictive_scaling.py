from datetime import datetime, timedelta, timezone
from scaling.predictive_scaling import is_spike_imminent

def test_is_spike_imminent_true():
    now = datetime.now(timezone.utc)
    kickoff = now + timedelta(minutes=20)
    schedule = [{"game_id": "G1", "kickoff_time": kickoff.isoformat()}]
    
    assert is_spike_imminent(schedule, lead_time_minutes=30) is True

def test_is_spike_imminent_false_future():
    now = datetime.now(timezone.utc)
    kickoff = now + timedelta(minutes=60)
    schedule = [{"game_id": "G1", "kickoff_time": kickoff.isoformat()}]
    
    assert is_spike_imminent(schedule, lead_time_minutes=30) is False

def test_is_spike_imminent_false_past():
    now = datetime.now(timezone.utc)
    kickoff = now - timedelta(minutes=10)
    schedule = [{"game_id": "G1", "kickoff_time": kickoff.isoformat()}]
    
    assert is_spike_imminent(schedule, lead_time_minutes=30) is False
