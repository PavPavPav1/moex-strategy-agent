from collections import defaultdict
from typing import Any, Dict, List


def build_diagnostics(result: Dict[str, Any]) -> Dict[str, Any]:
    metrics = result["metrics"]
    benchmark = result["buy_hold"]
    weaknesses: List[Dict[str, str]] = []
    if metrics["excess_return_pp"] < 0:
        weaknesses.append({
            "area": "Доходность",
            "evidence": f"Стратегия отстала от «купить и держать» на {abs(metrics['excess_return_pp']):.2f} п.п.",
            "interpretation": "Смена режима по SMA не компенсировала пропущенные движения и издержки на выбранном периоде.",
        })
    if metrics["max_drawdown_pct"] <= -15:
        weaknesses.append({
            "area": "Риск",
            "evidence": f"Максимальная просадка {metrics['max_drawdown_pct']:.2f}% ({metrics['max_drawdown_peak']} → {metrics['max_drawdown_trough']}).",
            "interpretation": "Даже выход в денежные средства не исключил существенного снижения капитала.",
        })
    if metrics["closed_trades"] < 5:
        weaknesses.append({
            "area": "Выборка",
            "evidence": f"Всего {metrics['closed_trades']} закрытых сделок.",
            "interpretation": "Оценки win rate и средней сделки статистически неустойчивы.",
        })
    if metrics["win_rate_pct"] is not None and metrics["win_rate_pct"] < 50:
        weaknesses.append({
            "area": "Качество сигналов",
            "evidence": f"Прибыльны только {metrics['win_rate_pct']:.2f}% закрытых сделок.",
            "interpretation": "На боковых участках пересечения SMA могут давать повторные убыточные входы и выходы.",
        })
    if metrics["sharpe_rf0"] is not None and metrics["sharpe_rf0"] < 0.5:
        weaknesses.append({
            "area": "Доходность на риск",
            "evidence": f"Sharpe при нулевой безрисковой ставке: {metrics['sharpe_rf0']:.2f}.",
            "interpretation": "Доходность слабо компенсирует дневную волатильность на этом историческом интервале.",
        })
    if not weaknesses:
        weaknesses.append({
            "area": "Ограничение вывода",
            "evidence": "Явного отставания по базовым метрикам не обнаружено.",
            "interpretation": "Это не доказывает устойчивость: нужны другие периоды, бумаги, издержки и out-of-sample проверка.",
        })

    yearly_equity: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for row in result["equity"]:
        yearly_equity[row["date"][:4]].append(row)
    yearly = []
    previous_strategy = metrics["initial_capital_rub"]
    previous_benchmark = metrics["initial_capital_rub"]
    for year, rows in sorted(yearly_equity.items()):
        strategy_end = rows[-1]["equity"]
        benchmark_end = rows[-1]["buy_hold"]
        strategy_return = (strategy_end / previous_strategy - 1) * 100
        benchmark_return = (benchmark_end / previous_benchmark - 1) * 100
        yearly.append({
            "year": year,
            "strategy_return_pct": round(strategy_return, 2),
            "buy_hold_return_pct": round(benchmark_return, 2),
            "excess_pp": round(strategy_return - benchmark_return, 2),
        })
        previous_strategy = strategy_end
        previous_benchmark = benchmark_end
    worst_year = min(yearly, key=lambda item: item["strategy_return_pct"]) if yearly else None
    if worst_year and worst_year["strategy_return_pct"] < 0:
        weaknesses.append({
            "area": "Неблагоприятный режим",
            "evidence": f"Худший календарный год — {worst_year['year']}: {worst_year['strategy_return_pct']:.2f}%.",
            "interpretation": "Проверь этот режим отдельно; один агрегированный результат скрывает неоднородность.",
        })
    return {
        "weaknesses": weaknesses,
        "yearly": yearly,
        "worst_trades": sorted(result["trades"], key=lambda item: item["net_pnl_rub"])[:5],
        "largest_price_moves": result["price_moves"][:10],
        "limitations": [
            "Исследован один тикер и один набор параметров; оптимизация по всей истории повышает риск подгонки.",
            "Не моделировались налоги, дивиденды, проскальзывание, частичное исполнение и ограничения ликвидности.",
            "Sharpe рассчитан по дневной доходности с нулевой безрисковой ставкой и годовизацией √252.",
            "Сопоставление новостей и цены — только календарное и лексическое, без утверждения причинности.",
        ],
    }
