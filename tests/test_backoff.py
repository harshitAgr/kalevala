"""Exponential backoff scheduling for queued items."""
from kalevala.pipeline import next_retry_delay_seconds


def test_backoff_ladder():
    # attempts 0..5 map to roughly 60, 120, 240, 480, 960, 1800 (cap)
    assert 45 <= next_retry_delay_seconds(0) <= 75
    assert 90 <= next_retry_delay_seconds(1) <= 150
    assert 180 <= next_retry_delay_seconds(2) <= 300
    assert 360 <= next_retry_delay_seconds(3) <= 600
    assert 720 <= next_retry_delay_seconds(4) <= 1200
    # cap at 30 min ± jitter
    for attempt in (5, 6, 10, 20):
        assert 1350 <= next_retry_delay_seconds(attempt) <= 2250
