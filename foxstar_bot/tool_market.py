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

@dataclass(frozen=True)
class MarketIndicators:
    symbol: str
    currency: str
    exchange: str
    interval: str
    range_window: str
    close_count: int
    latest_close: float | None
    sma_20: float | None
    sma_50: float | None
    sma_200: float | None
    ema_12: float | None
    ema_26: float | None
    rsi_14: float | None
    macd: float | None
    macd_signal: float | None
    macd_histogram: float | None

class YahooQuoteTool:
    def fetch_quote(self, symbol: str) -> MarketQuote:
        payload = self._fetch_chart(symbol, interval="1d", range_window="5d")
        meta = payload["meta"]
        price = _to_float(meta.get("regularMarketPrice"))
        previous = _to_float(meta.get("chartPreviousClose"))
        change = None
        change_percent = None
        if price is not None and previous not in (None, 0.0):
            change = price - previous
            change_percent = (change / previous) * 100.0
        return MarketQuote(
            symbol=str(meta.get("symbol") or str(symbol or "").strip().upper()),
            currency=str(meta.get("currency") or ""),
            exchange=str(meta.get("exchangeName") or ""),
            instrument_type=str(meta.get("instrumentType") or ""),
            market_state=str(meta.get("marketState") or ""),
            regular_market_price=price,
            chart_previous_close=previous,
            price_change=change,
            price_change_percent=change_percent,
        )

def _to_float(value: object) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None

def _sma(values: list[float], period: int) -> float | None:
    if len(values) < period:
        return None
    window = values[-period:]
    return sum(window) / period

def _ema_series(values: list[float], period: int) -> list[float | None]:
    if len(values) < period:
        return []
    multiplier = 2.0 / (period + 1.0)
    series: list[float | None] = [None] * (period - 1)
    ema = sum(values[:period]) / period
    series.append(ema)
    for value in values[period:]:
        ema = ((value - ema) * multiplier) + ema
        series.append(ema)
    return series

def _rsi(values: list[float], period: int) -> float | None:
    if len(values) <= period:
        return None
    gains: list[float] = []
    losses: list[float] = []
    for previous, current in zip(values[:-1], values[1:]):
        delta = current - previous
        gains.append(max(delta, 0.0))
        losses.append(abs(min(delta, 0.0)))
    average_gain = sum(gains[:period]) / period
    average_loss = sum(losses[:period]) / period
    for gain, loss in zip(gains[period:], losses[period:]):
        average_gain = ((average_gain * (period - 1)) + gain) / period
        average_loss = ((average_loss * (period - 1)) + loss) / period
    if average_loss == 0:
        return 100.0
    rs = average_gain / average_loss
    return 100.0 - (100.0 / (1.0 + rs))
