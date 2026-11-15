import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict

from .agent import StrategyAgent
from .models import AgentSession
from .moex_client import MOEXClient
from .news import NewsClient
from .tools import ToolExecutor, ToolRuntime


DEMO_STRATEGY = (
    "Проверь акцию SBER на MOEX с 2024-01-01 по 2025-12-31. "
    "Покупай, когда SMA(20) выше SMA(50), и продавай, когда SMA(20) ниже SMA(50). "
    "Начальный капитал 1 000 000 ₽, комиссия 5 б.п. на операцию. Без шорта и плеча."
)


def _load_config(path: Path) -> Dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _project_root(config_path: Path) -> Path:
    return config_path.resolve().parent.parent


def _parse_faults(values: list) -> Dict[str, list]:
    faults: Dict[str, list] = {}
    for value in values:
        if "=" not in value:
            raise ValueError("Формат ошибки: tool_name=timeout")
        name, kind = value.split("=", 1)
        faults.setdefault(name, []).append(kind)
    return faults


def _build_agent(args: argparse.Namespace) -> StrategyAgent:
    config_path = Path(args.config).resolve()
    root = _project_root(config_path)
    config = _load_config(config_path)
    cache_only = bool(args.cache_only or config.get("cache_only"))
    if getattr(args, "online", False):
        cache_only = False
    output = Path(args.output) if getattr(args, "output", None) else root / config["output_dir"]
    if not output.is_absolute():
        output = (Path.cwd() / output).resolve()
    output.mkdir(parents=True, exist_ok=True)
    session = AgentSession(run_dir=output)
    data_dir = Path(config["data_dir"])
    if not data_dir.is_absolute():
        data_dir = root / data_dir
    moex = MOEXClient(data_dir=data_dir, timeout_seconds=15, cache_only=cache_only)
    rss_path = Path(config["rss_sources_file"])
    if not rss_path.is_absolute():
        rss_path = root / rss_path
    sources = json.loads(rss_path.read_text(encoding="utf-8"))
    news = NewsClient(sources=sources, snapshot_path=data_dir / "news_snapshot.json")
    runtime = ToolRuntime(session=session, moex=moex, news=news, cache_only=cache_only)
    executor = ToolExecutor(
        runtime=runtime,
        attempts=int(config.get("tool_attempts", 2)),
        timeout_seconds=int(config.get("tool_timeout_seconds", 45)),
        max_result_chars=int(config.get("max_tool_result_chars", 12000)),
        faults=_parse_faults(getattr(args, "fault", [])),
    )
    text = DEMO_STRATEGY if args.command == "demo" else args.text
    def show(event: str, fields: Dict[str, Any]) -> None:
        if event == "tool_call":
            print(f"→ {fields['tool']} {json.dumps(fields['args'], ensure_ascii=False)}")
        elif event == "tool_error":
            print(f"  ошибка: {fields['error']['type']} — {fields['error']['message']}")
        elif event == "tool_result":
            print(f"  ✓ {fields['tool']}: успешно")
    return StrategyAgent(config=config, executor=executor, user_text=text, event_handler=show)


def main() -> None:
    parser = argparse.ArgumentParser(description="MOEX Strategy Agent — исследовательский бэктест SMA-стратегий")
    parser.add_argument("--config", default="config/agent.json")
    subparsers = parser.add_subparsers(dest="command", required=True)
    demo = subparsers.add_parser("demo", help="Воспроизводимое демо SBER")
    demo.add_argument("--cache-only", action="store_true", help="Не обращаться к сети")
    demo.add_argument("--online", action="store_true", help="Обновить данные из MOEX ISS и RSS")
    demo.add_argument("--output")
    demo.add_argument("--fault", action="append", default=[], help="Смодировать сбой, например backtest_moex_strategy=timeout")
    run = subparsers.add_parser("run", help="Запустить стратегию на естественном языке")
    run.add_argument("text")
    run.add_argument("--cache-only", action="store_true")
    run.add_argument("--output")
    run.add_argument("--fault", action="append", default=[])
    contracts = subparsers.add_parser("contracts", help="Показать контракты трёх инструментов")
    contracts.add_argument("--save", action="store_true", help="Сохранить docs/tool_contracts.json")
    args = parser.parse_args()
    try:
        if args.command == "contracts":
            config_path = Path(args.config).resolve()
            root = _project_root(config_path)
            runtime = ToolRuntime(AgentSession(root / ".contracts_tmp"), None, None)
            executor = ToolExecutor(runtime)
            payload = json.dumps(executor.export_contracts(), ensure_ascii=False, indent=2)
            print(payload)
            if args.save:
                target = root / "docs" / "tool_contracts.json"
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(payload + "\n", encoding="utf-8")
            return
        agent = _build_agent(args)
        response = agent.run()
        print("\n" + response)
        trace_path = agent.executor.trace_path
        if trace_path.exists():
            retries = []
            for line in trace_path.read_text(encoding="utf-8").splitlines():
                event = json.loads(line)
                if event.get("event") == "tool_error" and event.get("will_retry"):
                    retries.append(f"{event['tool']}: {event['error']['type']} → технический повтор")
            if retries:
                print("\nОбработанные сбои:")
                for item in retries:
                    print(f"- {item} → восстановлено")
    except (OSError, ValueError, KeyError) as exc:
        print(f"Ошибка запуска: {exc}", file=sys.stderr)
        raise SystemExit(2)


if __name__ == "__main__":
    main()
