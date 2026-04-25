from __future__ import annotations

import json

import urllib.parse

import urllib.request

from dataclasses import dataclass

YAHOO_CHART_ENDPOINT = "https://query1.finance.yahoo.com/v8/finance/chart/"

@dataclass(frozen=True)
class MarketQuote:
    symbol: str
    currency: str
    exchange: str
    instrument_type: str
    market_state: str
    regular_market_price: float | None
    chart_previous_close: float | None
    price_change: float | None
    price_change_percent: float | None

def _to_float(value: object) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
