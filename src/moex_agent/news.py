import json
import re
from datetime import date, datetime
from email.utils import parsedate_to_datetime
from html import unescape
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

import feedparser
import requests

from .errors import ServiceTimeout


COMPANY_TERMS = {
    "SBER": ["sber", "сбер", "сбербанк"],
    "GAZP": ["gazprom", "газпром"],
    "LKOH": ["lukoil", "лукойл"],
    "YDEX": ["yandex", "яндекс"],
    "TCS": ["tcs", "тинькофф", "т-банк"],
    "ROSN": ["rosneft", "роснефт"],
    "NOVATEK": ["novatek", "новатэк"],
    "MGNT": ["magnit", "магнит"],
    "PLZL": ["polyus", "полюс"],
    "GMKN": ["nornickel", "норникел"],
}


def _clean_html(value: str, limit: int = 500) -> str:
    text = unescape(re.sub(r"<[^>]+>", " ", value or ""))
    return re.sub(r"\s+", " ", text).strip()[:limit]


def _entry_date(entry: Dict[str, Any]) -> Optional[date]:
    for key in ("published", "updated"):
        raw = entry.get(key)
        if raw:
            try:
                return parsedate_to_datetime(raw).date()
            except (TypeError, ValueError):
                try:
                    return datetime.fromisoformat(str(raw).replace("Z", "+00:00")).date()
                except ValueError:
                    pass
    struct = entry.get("published_parsed") or entry.get("updated_parsed")
    if struct:
        return date(struct.tm_year, struct.tm_mon, struct.tm_mday)
    return None


class NewsClient:
    def __init__(self, sources: List[Dict[str, str]], timeout_seconds: int = 12, snapshot_path: Optional[Path] = None):
        self.sources = sources
        self.timeout_seconds = timeout_seconds
        self.snapshot_path = snapshot_path
        self.http = requests.Session()
        self.http.headers.update({"User-Agent": "moex-strategy-agent/1.0 educational-research"})

    def _load_snapshot(self) -> Optional[List[Dict[str, Any]]]:
        if not self.snapshot_path or not self.snapshot_path.exists():
            return None
        try:
            payload = json.loads(self.snapshot_path.read_text(encoding="utf-8"))
            return payload.get("items", payload) if isinstance(payload, dict) else payload
        except (OSError, ValueError):
            return None

    def collect(self, cache_only: bool = False) -> Dict[str, Any]:
        errors = []
        items: List[Dict[str, Any]] = []
        if cache_only:
            snapshot = self._load_snapshot()
            if snapshot is not None:
                return {
                    "items": snapshot[:300], "errors": [], "source": "offline_news_snapshot",
                    "warning": "Использована небольшая подборка открытых публикаций, а не полный архив RSS",
                }
            return {"items": [], "errors": [{"type": "not_found", "message": "Новостной снапшот не найден", "hint": "Запусти без --cache-only"}], "source": "unavailable"}
        for source in self.sources[:10]:
            try:
                response = self.http.get(source["url"], timeout=self.timeout_seconds)
                response.raise_for_status()
                parsed = feedparser.loads(response.content)
                if parsed.bozo and not parsed.entries:
                    raise ValueError("RSS не разобран")
                for entry in parsed.entries[:100]:
                    published = _entry_date(entry)
                    if not published:
                        continue
                    items.append({
                        "source": source["name"],
                        "title": _clean_html(entry.get("title", ""), 300),
                        "summary": _clean_html(entry.get("summary", ""), 500),
                        "url": entry.get("link", ""),
                        "published": published.isoformat(),
                    })
            except requests.Timeout:
                errors.append({"source": source["name"], "type": "timeout", "message": "RSS-лента не ответила вовремя"})
            except (requests.RequestException, ValueError) as exc:
                errors.append({"source": source["name"], "type": "feed_error", "message": str(exc)[:200]})
        if not items:
            snapshot = self._load_snapshot()
            if snapshot is not None:
                return {
                    "items": snapshot[:300], "errors": errors, "source": "offline_news_snapshot_after_error",
                    "warning": "Свежие RSS недоступны; использована небольшая подборка открытых публикаций, а не полный архив RSS",
                }
        unique = []
        seen = set()
        for item in items:
            key = item["url"] or (item["source"], item["title"], item["published"])
            if key not in seen:
                seen.add(key)
                unique.append(item)
        return {"items": unique[:300], "errors": errors, "source": "rss_live"}

    def match(self, moves: Iterable[Dict[str, Any]], ticker: str, top_n: int, window_days: int, cache_only: bool = False) -> Dict[str, Any]:
        collected = self.collect(cache_only=cache_only)
        terms = COMPANY_TERMS.get(ticker, [ticker.lower()])
        matches = []
        for move in list(moves)[:top_n]:
            move_date = date.fromisoformat(move["date"])
            nearby = []
            for item in collected["items"]:
                try:
                    published = date.fromisoformat(item["published"][:10])
                except (ValueError, KeyError):
                    continue
                distance = abs((published - move_date).days)
                haystack = f"{item.get('title', '')} {item.get('summary', '')}".lower()
                found_terms = [term for term in terms if term in haystack]
                if distance <= window_days and found_terms:
                    nearby.append({
                        "source": item["source"],
                        "title": item["title"],
                        "url": item["url"],
                        "published": item["published"],
                        "days_from_move": distance,
                        "matched_terms": found_terms,
                    })
            matches.append({
                "move": {key: value for key, value in move.items() if key != "abs_return_pct"},
                "news": nearby[:3],
                "statement": "Календарное и лексическое совпадение; причинно-следственная связь не установлена",
            })
        return {
            "ticker": ticker,
            "window_days": window_days,
            "matches": matches,
            "matched_moves": sum(bool(item["news"]) for item in matches),
            "rss_items_checked": len(collected["items"]),
            "source": collected["source"],
            "warning": collected.get("warning"),
            "errors": collected["errors"],
            "non_causality_notice": "Новости показаны как контекст рядом с крупными движениями цены. Это не доказательство причины движения.",
        }
