"""Backfill daily bars and write the analytics report for one or more symbols."""

import json
import sys
from pathlib import Path

from app.services.history import refresh_symbol_analytics


def main(symbols: list[str]) -> dict:
    reports = {}
    for symbol in symbols:
        print(f"analyzing {symbol}", flush=True)
        reports[symbol] = refresh_symbol_analytics(symbol, period="5y")
    out = Path("benchmarks/analytics.json")
    out.parent.mkdir(exist_ok=True)
    out.write_text(json.dumps(reports, indent=2))
    print(json.dumps(reports, indent=2))
    return reports


if __name__ == "__main__":
    chosen = sys.argv[1:] or ["AAPL", "MSFT", "SPY"]
    main(chosen)
