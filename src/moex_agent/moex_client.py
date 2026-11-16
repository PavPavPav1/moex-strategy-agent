import csv
import hashlib
import json
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional

import requests

from .errors import ServiceTimeout, ToolProblem
from .models import Candle, DataBundle, StrategySpec


class MOEXClient:
    def __init__(self, data_dir: Path, timeout_seconds: int = 15, cache_only: bool = False):
        self.data_dir = data_dir
        self.timeout_seconds = timeout_seconds
        self.cache_only = cache_only
        self.base_url = "https://iss.moex.com/iss/history/engines/stock/markets/shares/boards/TQBR/securities"
        self.http = requests.Session()
        self.http.headers.update({"User-Agent": "moex-strategy-agent/1.0 educational-research"})

    def _cache_base(self, spec: StrategySpec) -> Path:
        return self.data_dir / f"{spec.ticker}_{spec.date_from}_{spec.date_to}_24"

    def _cache_path(self, spec: StrategySpec) -> Path:
        return self._cache_base(spec).with_suffix(".csv")

    def _source_url(self, spec: StrategySpec) -> str:
        return (
            f"{self.base_url}/{spec.ticker}.json?from={spec.date_from}&till={spec.date_to}"
            "&iss.meta=off&history.columns=TRADEDATE,OPEN,CLOSE,HIGH,LOW,VOLUME"
        )

    def _request_page(self, spec: StrategySpec, start: int) -> Dict:
        url = f"{self.base_url}/{spec.ticker}.json"
        params = {
            "from": spec.date_from.isoformat(),
            "till": spec.date_to.isoformat(),
            "start": start,
            "iss.meta": "off",
            "history.columns": "TRADEDATE,OPEN,CLOSE,HIGH,LOW,VOLUME",
        }
        try:
            response = self.http.get(url, params=params, timeout=self.timeout_seconds)
            response.raise_for_status()
            payload = response.json()
        except requests.Timeout as exc:
            raise ServiceTimeout("MOEX ISS не ответил вовремя") from exc
        except requests.RequestException as exc:
            raise ToolProblem(
                "service_unavailable",
                "MOEX ISS недоступен",
                "Проверь сеть или запусти демо с --cache-only",
                True,
            ) from exc
        except ValueError as exc:
            raise ToolProblem("bad_response", "MOEX ISS вернул не JSON", "Повтори запрос позже", True) from exc
        if "history" not in payload or "columns" not in payload["history"]:
            raise ToolProblem("bad_response", "В ответе MOEX ISS нет блока history", "Проверь тикер и параметры запроса")
        return payload

    def _fetch_remote(self, spec: StrategySpec) -> List[Candle]:
        candles: List[Candle] = []
        start = 0
        deadline = time.monotonic() + 120
        while True:
            if time.monotonic() >= deadline:
                raise ServiceTimeout("Превышен общий лимит загрузки MOEX ISS (120 секунд)")
            payload = self._request_page(spec, start)
            block = payload["history"]
            rows = block.get("data") or []
            if start == 0 and not rows:
                raise ToolProblem("not_found", "MOEX ISS не вернул свечи", "Проверь тикер, board TQBR и период")
            columns = block["columns"]
            for row in rows:
                item = dict(zip(columns, row))
                if not all(item.get(key) is not None for key in ("TRADEDATE", "OPEN", "CLOSE", "HIGH", "LOW")):
                    raise ToolProblem("bad_response", "MOEX ISS вернул свечу с пропущенными ценами или датой", "Данные отклонены; проверь источник")
                candles.append(Candle(
                    tradedate=item["TRADEDATE"],
                    open=float(item["OPEN"]),
                    close=float(item["CLOSE"]),
                    high=float(item["HIGH"]),
                    low=float(item["LOW"]),
                    volume=float(item.get("VOLUME") or 0),
                ))
            cursor = payload.get("history.cursor", {})
            cursor_rows = cursor.get("data") or []
            total = dict(zip(cursor.get("columns", []), cursor_rows[0])).get("TOTAL", len(candles)) if cursor_rows else len(candles)
            if not rows or start + len(rows) >= int(total):
                break
            start += len(rows)
            if start > 100_000:
                raise ToolProblem("limit_exceeded", "Слишком много строк в ответе MOEX", "Сократи период")
        unique = {candle.tradedate: candle for candle in candles}
        ordered = [unique[key] for key in sorted(unique)]
        if len(ordered) < spec.slow_window + 2:
            raise ToolProblem("insufficient_data", "Недостаточно свечей для расчёта медленной SMA", "Увеличь период или уменьши slow_window")
        return ordered

    def _save_cache(self, spec: StrategySpec, candles: List[Candle]) -> DataBundle:
        self.data_dir.mkdir(parents=True, exist_ok=True)
        path = self._cache_path(spec)
        with path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.writer(handle)
            writer.writerow(["tradedate", "open", "close", "high", "low", "volume"])
            for candle in candles:
                writer.writerow([
                    candle.tradedate.isoformat(), candle.open, candle.close,
                    candle.high, candle.low, candle.volume,
                ])
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        fetched_at = datetime.now(timezone.utc).isoformat()
        metadata = {
            "source": "MOEX ISS",
            "source_url": self._source_url(spec),
            "fetched_at": fetched_at,
            "rows": len(candles),
            "sha256": digest,
        }
        self._cache_base(spec).with_suffix(".json").write_text(
            json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        return DataBundle(candles, "moex_iss", self._source_url(spec), str(path), fetched_at=fetched_at, sha256=digest)

    def _load_cache(self, spec: StrategySpec, source: str, warning: Optional[str] = None) -> DataBundle:
        path = self._cache_path(spec)
        metadata_path = self._cache_base(spec).with_suffix(".json")
        if not path.exists():
            raise ToolProblem("not_found", "Локальный снапшот не найден", "Запусти без --cache-only при доступной сети")
        candles: List[Candle] = []
        try:
            with path.open(encoding="utf-8", newline="") as handle:
                for row in csv.DictReader(handle):
                    candles.append(Candle(**row))
        except (OSError, ValueError) as exc:
            raise ToolProblem("bad_cache", "Не удалось прочитать локальный снапшот", "Удали повреждённый CSV и загрузи данные заново") from exc
        metadata = {}
        if metadata_path.exists():
            metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        if not metadata.get("sha256") or metadata["sha256"] != digest:
            raise ToolProblem("bad_cache", "SHA-256 снапшота отсутствует или не совпадает", "Сохрани повреждённый файл отдельно и заново загрузи данные")
        if len(candles) < spec.slow_window + 2:
            raise ToolProblem("insufficient_data", "Недостаточно свечей в снапшоте", "Увеличь период")
        return DataBundle(
            candles=candles,
            source=source,
            source_url=metadata.get("source_url", self._source_url(spec)),
            cache_path=str(path),
            warning=warning,
            fetched_at=metadata.get("fetched_at"),
            sha256=metadata.get("sha256"),
        )

    def fetch(self, spec: StrategySpec) -> DataBundle:
        if self.cache_only:
            return self._load_cache(spec, "iss_cache")
        try:
            return self._save_cache(spec, self._fetch_remote(spec))
        except ToolProblem as exc:
            if exc.kind in {"timeout", "service_unavailable", "bad_response"} and self._cache_path(spec).exists():
                return self._load_cache(
                    spec,
                    "iss_cache_after_error",
                    f"Сеть недоступна ({exc.kind}); использован ранее сохранённый снапшот MOEX ISS",
                )
            raise
