#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
python -m moex_agent.cli demo --cache-only --fault backtest_moex_strategy=timeout
pytest
