import json

from moex_agent.news import NewsClient


def test_news_match_is_non_causal(tmp_path):
    snapshot = tmp_path / "news.json"
    snapshot.write_text(json.dumps({"items": [{
        "source": "Test RSS", "title": "Новость Сбербанка", "summary": "Открытая публикация",
        "url": "https://example.com/news", "published": "2024-12-20",
    }]}), encoding="utf-8")
    client = NewsClient(sources=[], snapshot_path=snapshot)
    moves = [{"date": "2024-12-20", "close": 257.6, "return_pct": 12.49, "abs_return_pct": 12.49}]
    result = client.match(moves, "SBER", top_n=1, window_days=0, cache_only=True)
    assert result["matched_moves"] == 1
    assert result["matches"][0]["news"][0]["url"] == "https://example.com/news"
    assert "не доказательство" in result["non_causality_notice"]
    assert "причинно-следственная связь не установлена" in result["matches"][0]["statement"]


def test_unrelated_news_is_not_attached(tmp_path):
    snapshot = tmp_path / "news.json"
    snapshot.write_text(json.dumps([{"source": "RSS", "title": "Погода", "summary": "Снег", "url": "https://example.com", "published": "2024-01-01"}]), encoding="utf-8")
    result = NewsClient([], snapshot_path=snapshot).match([{"date": "2024-01-01", "return_pct": 5, "close": 100}], "SBER", 1, 1, True)
    assert result["matched_moves"] == 0
    assert result["matches"][0]["news"] == []


def test_missing_snapshot_is_honest_error(tmp_path):
    result = NewsClient([], snapshot_path=tmp_path / "missing.json").collect(cache_only=True)
    assert result["items"] == []
    assert result["errors"][0]["type"] == "not_found"
