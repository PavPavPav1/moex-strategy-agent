import pytest

from moex_agent.errors import ServiceTimeout, ToolProblem
from moex_agent.moex_client import MOEXClient


def test_cache_roundtrip(tmp_path, spec, candles):
    client = MOEXClient(tmp_path, cache_only=True)
    saved = client._save_cache(spec, candles)
    loaded = client.fetch(spec)
    assert len(loaded.candles) == len(candles)
    assert loaded.source == "iss_cache"
    assert loaded.sha256 == saved.sha256
    assert loaded.candles[0].tradedate == candles[0].tradedate


def test_network_failure_uses_marked_cache(tmp_path, spec, candles, monkeypatch):
    client = MOEXClient(tmp_path, cache_only=False)
    client._save_cache(spec, candles)
    def fail(_):
        raise ServiceTimeout()
    monkeypatch.setattr(client, "_fetch_remote", fail)
    loaded = client.fetch(spec)
    assert loaded.source == "iss_cache_after_error"
    assert "timeout" in loaded.warning


def test_missing_cache_returns_not_found(tmp_path, spec):
    client = MOEXClient(tmp_path, cache_only=True)
    with pytest.raises(ToolProblem) as error:
        client.fetch(spec)
    assert error.value.kind == "not_found"
