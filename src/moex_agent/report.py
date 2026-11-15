import base64
import csv
import hashlib
import html
import json
from io import BytesIO
from pathlib import Path
from typing import Any, Dict, List

import matplotlib
matplotlib.use("Agg")
import matplotlib.dates as mdates
import matplotlib.pyplot as plt
import pandas as pd

from .models import AgentSession, DISCLAIMER


PURPLE = "#6750A4"
TEAL = "#0F9D8A"
RED = "#C64756"
INK = "#17233C"
MUTED = "#667085"
BG = "#F5F7FB"


def _rub(value: float) -> str:
    return f"{value:,.0f} ₽".replace(",", " ")


def _pct(value: float) -> str:
    return f"{value:+.2f}%"


def _plot_charts(result: Dict[str, Any], run_dir: Path) -> Dict[str, str]:
    plt.rcParams.update({
        "font.family": "DejaVu Sans", "font.size": 10, "axes.titleweight": "bold",
        "axes.edgecolor": "#D0D5DD", "axes.labelcolor": MUTED, "text.color": INK,
        "xtick.color": MUTED, "ytick.color": MUTED, "axes.titlecolor": INK,
    })
    frame = pd.DataFrame(result["equity"])
    frame["date"] = pd.to_datetime(frame["date"])
    charts: Dict[str, str] = {}

    fig, ax = plt.subplots(figsize=(11, 5.2), facecolor="white")
    ax.plot(frame["date"], frame["equity"], color=PURPLE, linewidth=2.4, label="SMA-стратегия")
    ax.plot(frame["date"], frame["buy_hold"], color=TEAL, linewidth=2.0, label="Купить и держать")
    ax.set_title("Кривая капитала", loc="left", fontsize=16, pad=16)
    ax.set_ylabel("Капитал, млн ₽")
    ax.yaxis.set_major_formatter(lambda value, _: f"{value / 1_000_000:.2f}")
    ax.grid(axis="y", alpha=0.18)
    ax.spines[["top", "right"]].set_visible(False)
    ax.legend(frameon=False, loc="upper left")
    ax.xaxis.set_major_locator(mdates.AutoDateLocator(minticks=5, maxticks=9))
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%m.%Y"))
    fig.tight_layout()
    fig.savefig(run_dir / "equity.png", dpi=170, bbox_inches="tight")
    plt.close(fig)
    charts["equity"] = "equity.png"

    strategy_dd = (frame["equity"] / frame["equity"].cummax() - 1) * 100
    benchmark_dd = (frame["buy_hold"] / frame["buy_hold"].cummax() - 1) * 100
    fig, ax = plt.subplots(figsize=(11, 4.4), facecolor="white")
    ax.fill_between(frame["date"], strategy_dd, 0, color=PURPLE, alpha=0.20)
    ax.plot(frame["date"], strategy_dd, color=PURPLE, linewidth=1.8, label="SMA-стратегия")
    ax.plot(frame["date"], benchmark_dd, color=TEAL, linewidth=1.5, label="Купить и держать")
    ax.set_title("Просадка от локального максимума", loc="left", fontsize=16, pad=16)
    ax.set_ylabel("Просадка, %")
    ax.grid(axis="y", alpha=0.18)
    ax.spines[["top", "right"]].set_visible(False)
    ax.legend(frameon=False, loc="lower left")
    ax.xaxis.set_major_locator(mdates.AutoDateLocator(minticks=5, maxticks=9))
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%m.%Y"))
    fig.tight_layout()
    fig.savefig(run_dir / "drawdown.png", dpi=170, bbox_inches="tight")
    plt.close(fig)
    charts["drawdown"] = "drawdown.png"

    fig, ax = plt.subplots(figsize=(11, 5.2), facecolor="white")
    ax.plot(frame["date"], frame["close"], color="#98A2B3", linewidth=1.5, label=f"{result['strategy']['ticker']} close")
    ax.plot(frame["date"], frame["fast_sma"], color=PURPLE, linewidth=1.7, label=f"SMA {result['strategy']['fast_window']}")
    ax.plot(frame["date"], frame["slow_sma"], color=TEAL, linewidth=1.7, label=f"SMA {result['strategy']['slow_window']}")
    entries = [row for row in result["trades"]]
    if entries:
        entry_dates = pd.to_datetime([row["entry_date"] for row in entries])
        entry_prices = [row["entry_price_rub"] for row in entries]
        exit_dates = pd.to_datetime([row["exit_date"] for row in entries])
        exit_prices = [row["exit_price_rub"] for row in entries]
        ax.scatter(entry_dates, entry_prices, marker="^", s=55, color=PURPLE, zorder=5, label="Вход")
        ax.scatter(exit_dates, exit_prices, marker="v", s=55, color=RED, zorder=5, label="Выход")
    ax.set_title("Цена, скользящие средние и сделки", loc="left", fontsize=16, pad=16)
    ax.set_ylabel("Цена, ₽")
    ax.grid(axis="y", alpha=0.18)
    ax.spines[["top", "right"]].set_visible(False)
    ax.legend(frameon=False, ncol=3, loc="upper left")
    ax.xaxis.set_major_locator(mdates.AutoDateLocator(minticks=5, maxticks=9))
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%m.%Y"))
    fig.tight_layout()
    fig.savefig(run_dir / "signals.png", dpi=170, bbox_inches="tight")
    plt.close(fig)
    charts["signals"] = "signals.png"

    yearly = result["diagnostics"]["yearly"]
    if yearly:
        years = [row["year"] for row in yearly]
        strategy_values = [row["strategy_return_pct"] for row in yearly]
        benchmark_values = [row["buy_hold_return_pct"] for row in yearly]
        positions = list(range(len(years)))
        fig, ax = plt.subplots(figsize=(9, 4.5), facecolor="white")
        width = 0.34
        ax.bar([value - width / 2 for value in positions], strategy_values, width, color=PURPLE, label="SMA-стратегия")
        ax.bar([value + width / 2 for value in positions], benchmark_values, width, color=TEAL, label="Купить и держать")
        ax.axhline(0, color="#98A2B3", linewidth=0.8)
        ax.set_xticks(positions, years)
        ax.set_ylabel("Доходность, %")
        ax.set_title("Доходность по календарным годам", loc="left", fontsize=16, pad=16)
        ax.grid(axis="y", alpha=0.18)
        ax.spines[["top", "right"]].set_visible(False)
        ax.legend(frameon=False)
        fig.tight_layout()
        fig.savefig(run_dir / "yearly.png", dpi=170, bbox_inches="tight")
        plt.close(fig)
        charts["yearly"] = "yearly.png"
    return charts


def _image_data(path: Path) -> str:
    return "data:image/png;base64," + base64.b64encode(path.read_bytes()).decode("ascii")


def _write_csv(path: Path, rows: List[Dict[str, Any]]) -> None:
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def _metrics_table(metrics: Dict[str, Any], benchmark: Dict[str, Any]) -> str:
    rows = [
        ("Итоговый капитал", _rub(metrics["final_equity_rub"]), _rub(benchmark["final_equity_rub"])),
        ("Доходность", _pct(metrics["total_return_pct"]), _pct(benchmark["total_return_pct"])),
        ("CAGR", _pct(metrics["cagr_pct"]), _pct(benchmark["cagr_pct"])),
        ("Макс. просадка", _pct(metrics["max_drawdown_pct"]), _pct(benchmark["max_drawdown_pct"])),
        ("Волатильность", _pct(metrics["annualized_volatility_pct"]), _pct(benchmark["annualized_volatility_pct"])),
        ("Sharpe, rf=0", str(metrics["sharpe_rf0"]), str(benchmark["sharpe_rf0"])),
        ("Закрытые сделки", str(metrics["closed_trades"]), str(benchmark["closed_trades"])),
        ("Win rate", f"{metrics['win_rate_pct']}%" if metrics["win_rate_pct"] is not None else "—", "—"),
        ("Время в позиции", f"{metrics['exposure_pct']}%", f"{benchmark['exposure_pct']}%"),
        ("Комиссии", _rub(metrics["total_fees_rub"]), _rub(benchmark["total_fees_rub"])),
    ]
    body = "".join(f"<tr><td>{html.escape(label)}</td><td>{html.escape(left)}</td><td>{html.escape(right)}</td></tr>" for label, left, right in rows)
    return f"<table><thead><tr><th>Метрика</th><th>SMA-стратегия</th><th>Купить и держать</th></tr></thead><tbody>{body}</tbody></table>"


def _render_html(session: AgentSession, charts: Dict[str, str]) -> str:
    result = session.result
    spec = result["strategy"]
    metrics = result["metrics"]
    benchmark = result["buy_hold"]
    diagnostics = result["diagnostics"]
    data = result["data"]
    check = result["crosscheck"]
    warning = f"<div class='warning'>{html.escape(data['warning'])}</div>" if data.get("warning") else ""
    assumptions = "".join(f"<li>{html.escape(item)}</li>" for item in session.assumptions)
    weaknesses = "".join(
        f"<article class='finding'><span>{html.escape(item['area'])}</span><strong>{html.escape(item['evidence'])}</strong><p>{html.escape(item['interpretation'])}</p></article>"
        for item in diagnostics["weaknesses"]
    )
    trade_rows = "".join(
        f"<tr><td>{row['entry_date']}</td><td>{row['exit_date']}</td><td>{row['quantity']}</td><td>{row['return_pct']:+.2f}%</td><td>{_rub(row['net_pnl_rub'])}</td><td>{html.escape(row['exit_reason'])}</td></tr>"
        for row in result["trades"]
    ) or "<tr><td colspan='6'>Закрытых сделок нет</td></tr>"
    yearly_rows = "".join(
        f"<tr><td>{row['year']}</td><td>{row['strategy_return_pct']:+.2f}%</td><td>{row['buy_hold_return_pct']:+.2f}%</td><td>{row['excess_pp']:+.2f} п.п.</td></tr>"
        for row in diagnostics["yearly"]
    )
    news_html = ""
    if session.news:
        cards = []
        for match in session.news["matches"]:
            move = match["move"]
            items = "".join(
                f"<li><a href='{html.escape(item['url'], quote=True)}' target='_blank' rel='noopener'>{html.escape(item['title'])}</a><small>{html.escape(item['source'])} · {item['published']} · Δ {item['days_from_move']} дн.</small></li>"
                for item in match["news"]
            ) or "<p class='muted'>Публикаций с названием компании в заданном окне не найдено.</p>"
            cards.append(f"<article class='news-card'><strong>{move['date']} · {move['return_pct']:+.2f}%</strong><ul>{items}</ul><small>{html.escape(match['statement'])}</small></article>")
        news_warning = f"<div class='warning'>{html.escape(session.news['warning'])}</div>" if session.news.get("warning") else ""
        news_html = (
            f"<section><div class='section-head'><span>04</span><h2>Цена ↔ новости</h2></div>"
            f"<p>Проверено публикаций: {session.news['rss_items_checked']}. Источник: {html.escape(session.news['source'])}. "
            f"Движений с совпадениями: {session.news['matched_moves']}.</p>{news_warning}"
            f"<div class='news-grid'>{''.join(cards)}</div><div class='warning'>{html.escape(session.news['non_causality_notice'])}</div></section>"
        )
    return f"""<!doctype html>
<html lang="ru"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>MOEX Strategy Agent · {html.escape(spec['ticker'])}</title>
<style>
:root{{--ink:{INK};--muted:{MUTED};--purple:{PURPLE};--teal:{TEAL};--bg:{BG};}}
*{{box-sizing:border-box}}body{{margin:0;background:var(--bg);color:var(--ink);font:15px/1.55 -apple-system,BlinkMacSystemFont,"Segoe UI",Arial,sans-serif}}
.hero{{background:linear-gradient(130deg,#10182f,#263b65 65%,#6750a4);color:white;padding:58px max(5vw,28px) 48px}}
.eyebrow{{font-size:12px;letter-spacing:.16em;text-transform:uppercase;opacity:.7}}h1{{font-size:42px;line-height:1.08;margin:12px 0 16px;max-width:900px}}.hero p{{max-width:850px;opacity:.82;font-size:17px}}
.badges{{display:flex;gap:10px;flex-wrap:wrap;margin-top:24px}}.badge{{padding:7px 12px;border:1px solid #ffffff44;border-radius:999px;background:#ffffff10;font-size:12px}}
main{{max-width:1200px;margin:-20px auto 60px;padding:0 24px}}section,.panel{{background:white;border:1px solid #e4e7ec;border-radius:20px;padding:28px;margin:20px 0;box-shadow:0 8px 30px #10182808}}
.section-head{{display:flex;align-items:center;gap:12px;margin-bottom:20px}}.section-head span{{color:var(--purple);font-weight:800;font-size:12px}}h2{{font-size:24px;margin:0}}h3{{margin:0 0 10px}}p{{color:var(--muted)}}
.kpis{{display:grid;grid-template-columns:repeat(4,1fr);gap:14px}}.kpi{{background:white;border:1px solid #e4e7ec;border-radius:16px;padding:22px}}.kpi small{{color:var(--muted);text-transform:uppercase;letter-spacing:.08em}}.kpi strong{{display:block;font-size:28px;margin-top:8px}}.positive{{color:var(--teal)}}.negative{{color:#c64756}}
.grid{{display:grid;grid-template-columns:1fr 1fr;gap:20px}}img{{width:100%;border-radius:10px}}table{{width:100%;border-collapse:collapse;font-size:14px}}th{{text-align:left;color:var(--muted);font-size:12px;text-transform:uppercase;letter-spacing:.05em}}th,td{{padding:11px 8px;border-bottom:1px solid #eaecf0}}td:nth-child(n+2),th:nth-child(n+2){{text-align:right}}.scroll{{overflow:auto}}
.finding{{border-left:3px solid var(--purple);padding:4px 0 4px 18px;margin:18px 0}}.finding span{{font-size:11px;text-transform:uppercase;color:var(--purple);font-weight:700}}.finding strong{{display:block;margin:4px 0}}.finding p{{margin:0}}
.warning{{background:#fff7e8;border:1px solid #fedf89;color:#854a0e;padding:14px 16px;border-radius:12px;margin-top:18px}}.disclaimer{{background:#eef2ff;border-color:#c7d7fe;color:#3538cd;font-weight:600}}
.news-grid{{display:grid;grid-template-columns:1fr 1fr;gap:14px}}.news-card{{background:#f9fafb;border-radius:12px;padding:16px}}.news-card li{{margin:10px 0}}.news-card small{{display:block;color:var(--muted)}}a{{color:var(--purple);text-decoration:none}}.muted{{color:var(--muted)}}code{{background:#f2f4f7;padding:2px 5px;border-radius:5px}}
footer{{text-align:center;color:var(--muted);font-size:12px;padding:24px}}@media(max-width:800px){{.kpis{{grid-template-columns:1fr 1fr}}.grid,.news-grid{{grid-template-columns:1fr}}h1{{font-size:32px}}}}
</style></head><body>
<header class="hero"><div class="eyebrow">MOEX Strategy Agent · исследовательский отчёт</div><h1>{html.escape(spec['ticker'])}: SMA {spec['fast_window']} / {spec['slow_window']}</h1>
<p>{spec['date_from']} — {spec['date_to']} · {result['period']['sessions']} торговых сессий · капитал {_rub(spec['initial_capital_rub'])} · комиссия {spec['fee_bps']} б.п.</p>
<div class="badges"><span class="badge">Данные: {html.escape(data['source'])}</span><span class="badge">Сверка: {check['status']}</span><span class="badge">Next-open execution</span><span class="badge">Long only</span></div></header>
<main>
<div class="kpis"><div class="kpi"><small>Доходность</small><strong class="{'positive' if metrics['total_return_pct'] >= 0 else 'negative'}">{_pct(metrics['total_return_pct'])}</strong></div>
<div class="kpi"><small>Buy & hold</small><strong>{_pct(benchmark['total_return_pct'])}</strong></div>
<div class="kpi"><small>Макс. просадка</small><strong class="negative">{_pct(metrics['max_drawdown_pct'])}</strong></div>
<div class="kpi"><small>Сделок / отставание</small><strong>{metrics['closed_trades']} <span style="font-size:16px">/ {metrics['excess_return_pp']:+.2f} п.п.</span></strong></div></div>
{warning}
<section><div class="section-head"><span>01</span><h2>Капитал и риск</h2></div><img src="{_image_data(session.run_dir / charts['equity'])}" alt="Кривая капитала"><img src="{_image_data(session.run_dir / charts['drawdown'])}" alt="Просадка"></section>
<section><div class="section-head"><span>02</span><h2>Сравнение метрик</h2></div><div class="scroll">{_metrics_table(metrics, benchmark)}</div>
<div class="grid"><div><h3>Независимая сверка</h3><p>Две реализации сравнили {check['sessions_compared']} точек капитала и {check['primary_trades']} сделок.</p><ul><li>Макс. расхождение капитала: <b>{check['max_abs_equity_difference_rub']} ₽</b></li><li>Расхождение PnL: <b>{check['max_abs_trade_pnl_difference_rub']} ₽</b></li><li>SHA-256 кривой: <code>{check['primary_equity_sha256'][:16]}…</code></li></ul></div><div><h3>Допущения</h3><ul>{assumptions}</ul></div></div></section>
<section><div class="section-head"><span>03</span><h2>Где стратегия работает плохо</h2></div>{weaknesses}<img src="{_image_data(session.run_dir / charts['signals'])}" alt="Сигналы">
<div class="grid"><div><h3>По годам</h3><table><thead><tr><th>Год</th><th>SMA</th><th>B&H</th><th>Разница</th></tr></thead><tbody>{yearly_rows}</tbody></table></div><div><h3>Журнал сделок</h3><div class="scroll"><table><thead><tr><th>Вход</th><th>Выход</th><th>Шт.</th><th>Доходность</th><th>PnL</th><th>Выход</th></tr></thead><tbody>{trade_rows}</tbody></table></div></div></div></section>
{news_html}
<section><div class="section-head"><span>05</span><h2>Границы вывода</h2></div><ul>{''.join(f'<li>{html.escape(item)}</li>' for item in diagnostics['limitations'])}</ul><p>Источник котировок: <a href="{html.escape(data['source_url'], quote=True)}">MOEX ISS</a>. Снапшот SHA-256: <code>{html.escape(str(data.get('sha256')))}</code>.</p><div class="warning disclaimer">{html.escape(DISCLAIMER)}</div></section>
</main><footer>Сформировано MOEX Strategy Agent · воспроизводимые CSV, JSON и trace приложены</footer></body></html>"""


def _render_markdown(session: AgentSession) -> str:
    result = session.result
    metrics = result["metrics"]
    benchmark = result["buy_hold"]
    check = result["crosscheck"]
    lines = [
        f"# {result['strategy']['ticker']}: SMA {result['strategy']['fast_window']} / {result['strategy']['slow_window']}",
        "",
        f"Период: {result['period']['first']} — {result['period']['last']}; сессий: {result['period']['sessions']}.",
        f"Источник данных: **{result['data']['source']}**; независимая сверка: **{check['status']}**.",
        "",
        "## Ключевые метрики",
        "",
        "| Метрика | SMA | Купить и держать |",
        "|---|---:|---:|",
        f"| Итоговый капитал | {_rub(metrics['final_equity_rub'])} | {_rub(benchmark['final_equity_rub'])} |",
        f"| Доходность | {metrics['total_return_pct']:+.2f}% | {benchmark['total_return_pct']:+.2f}% |",
        f"| CAGR | {metrics['cagr_pct']:+.2f}% | {benchmark['cagr_pct']:+.2f}% |",
        f"| Макс. просадка | {metrics['max_drawdown_pct']:+.2f}% | {benchmark['max_drawdown_pct']:+.2f}% |",
        f"| Sharpe (rf=0) | {metrics['sharpe_rf0']} | {benchmark['sharpe_rf0']} |",
        f"| Закрытые сделки | {metrics['closed_trades']} | {benchmark['closed_trades']} |",
        f"| Win rate | {metrics['win_rate_pct']}% | — |",
        "",
        "![Кривая капитала](equity.png)",
        "",
        "![Просадка](drawdown.png)",
        "",
        "## Где стратегия работает плохо",
        "",
    ]
    for item in result["diagnostics"]["weaknesses"]:
        lines.extend([f"### {item['area']}", "", f"**{item['evidence']}**", "", item["interpretation"], ""])
    lines.extend([
        "## Независимая сверка", "",
        f"Сравнено {check['sessions_compared']} точек и {check['primary_trades']} сделок. "
        f"Максимальное расхождение капитала: {check['max_abs_equity_difference_rub']} ₽; "
        f"PnL: {check['max_abs_trade_pnl_difference_rub']} ₽.", "",
        "## Допущения", "",
    ])
    lines.extend([f"- {item}" for item in session.assumptions])
    lines.extend(["", "## Цена ↔ новости", ""])
    if session.news:
        lines.append(session.news["non_causality_notice"])
        lines.append("")
        for match in session.news["matches"]:
            move = match["move"]
            lines.append(f"### {move['date']}: {move['return_pct']:+.2f}%")
            lines.append("")
            if not match["news"]:
                lines.append("Подходящих публикаций не найдено.")
            for item in match["news"]:
                lines.append(f"- [{item['title']}]({item['url']}) — {item['source']}, {item['published']}")
            lines.append("")
    else:
        lines.append("Инструмент новостей не вызывался.")
    lines.extend(["", "## Ограничения", ""])
    lines.extend([f"- {item}" for item in result["diagnostics"]["limitations"]])
    lines.extend(["", f"> {DISCLAIMER}", ""])
    return "\n".join(lines)


def generate_report(session: AgentSession) -> Dict[str, str]:
    if session.result is None:
        raise ValueError("Нет результата бэктеста")
    run_dir = session.run_dir
    run_dir.mkdir(parents=True, exist_ok=True)
    result = session.result
    (run_dir / "strategy.json").write_text(json.dumps({"strategy": result["strategy"], "assumptions": session.assumptions}, ensure_ascii=False, indent=2), encoding="utf-8")
    (run_dir / "metrics.json").write_text(json.dumps({"metrics": result["metrics"], "buy_hold": result["buy_hold"], "data": result["data"]}, ensure_ascii=False, indent=2), encoding="utf-8")
    (run_dir / "crosscheck.json").write_text(json.dumps(result["crosscheck"], ensure_ascii=False, indent=2), encoding="utf-8")
    (run_dir / "diagnostics.json").write_text(json.dumps(result["diagnostics"], ensure_ascii=False, indent=2), encoding="utf-8")
    (run_dir / "news_matches.json").write_text(json.dumps(session.news or {"status": "not_requested"}, ensure_ascii=False, indent=2), encoding="utf-8")
    _write_csv(run_dir / "trades.csv", result["trades"])
    _write_csv(run_dir / "equity.csv", result["equity"])
    charts = _plot_charts(result, run_dir)
    (run_dir / "report.html").write_text(_render_html(session, charts), encoding="utf-8")
    (run_dir / "report.md").write_text(_render_markdown(session), encoding="utf-8")
    manifest = {}
    for path in sorted(run_dir.iterdir()):
        if path.is_file() and path.name not in {"manifest.json", "trace.jsonl"}:
            manifest[path.name] = {"bytes": path.stat().st_size, "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
    (run_dir / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"html": "report.html", "markdown": "report.md", "run_dir": str(run_dir)}
