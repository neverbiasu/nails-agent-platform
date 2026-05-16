"""Unit tests for SignalCollector (mock data, no network required)."""

from __future__ import annotations

from nails_agent.tools.fetchers.signal_collector import SignalCollector


def test_signal_collector_mock_data():
    collector = SignalCollector(mock_data_path="web/data/trend_signals.json")
    signals = collector.collect(keywords=["猫眼"], limit_per_kw=5)
    # Should return signals from mock data (or empty list if file missing)
    assert isinstance(signals, list)


def test_signal_collector_source_status():
    collector = SignalCollector(mock_data_path="web/data/trend_signals.json")
    status = collector.source_status()
    assert isinstance(status, dict)
    # mock source should always be available
    assert "mock" in status


def test_signal_collector_empty_keywords():
    collector = SignalCollector(mock_data_path="web/data/trend_signals.json")
    signals = collector.collect(keywords=[], limit_per_kw=10)
    assert isinstance(signals, list)
