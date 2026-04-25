from __future__ import annotations

import json

import math

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
    period_high_52w: float | None
    period_low_52w: float | None
    avg_volume_20: float | None
    vwap_session: float | None
    sma_10: float | None
    sma_20: float | None
    sma_50: float | None
    sma_100: float | None
    sma_200: float | None
    ema_9: float | None
    ema_12: float | None
    ema_20: float | None
    ema_26: float | None
    ema_50: float | None
    rsi_14: float | None
    macd: float | None
    macd_signal: float | None
    macd_histogram: float | None
    bollinger_middle_20: float | None
    bollinger_upper_20_2: float | None
    bollinger_lower_20_2: float | None
    bollinger_bandwidth: float | None
    bollinger_percent_b: float | None
    atr_14: float | None
    stochastic_k_14: float | None
    stochastic_d_3: float | None
    adx_14: float | None
    plus_di_14: float | None
    minus_di_14: float | None
    cci_20: float | None
    williams_r_14: float | None
    roc_12: float | None
    momentum_10: float | None
    obv: float | None
    distance_to_sma_50_percent: float | None
    distance_to_sma_200_percent: float | None

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

    def fetch_indicators(
        self,
        symbol: str,
        interval: str = "1d",
        range_window: str = "6mo",
    ) -> MarketIndicators:
        payload = self._fetch_chart(symbol, interval=interval, range_window=range_window)
        meta = payload["meta"]
        opens = payload["open_prices"]
        highs = payload["high_prices"]
        lows = payload["low_prices"]
        closes = payload["close_prices"]
        volumes = payload["volume_values"]

        latest_close = _last_non_none(closes)
        ema_9_series = _ema_series(closes, 9)
        ema_12_series = _ema_series(closes, 12)
        ema_20_series = _ema_series(closes, 20)
        ema_26_series = _ema_series(closes, 26)
        ema_50_series = _ema_series(closes, 50)

        macd_series = _pairwise_diff(ema_12_series, ema_26_series)
        macd_signal_series = _ema_series(macd_series, 9)
        macd = _last_non_none(macd_series)
        macd_signal = _last_non_none(macd_signal_series)
        macd_histogram = None
        if macd is not None and macd_signal is not None:
            macd_histogram = macd - macd_signal

        bollinger_middle, bollinger_upper, bollinger_lower = _bollinger_bands(closes, 20, 2.0)
        bollinger_bandwidth = None
        bollinger_percent_b = None
        if (
            bollinger_middle not in (None, 0.0)
            and bollinger_upper is not None
            and bollinger_lower is not None
        ):
            band_span = bollinger_upper - bollinger_lower
            bollinger_bandwidth = band_span / bollinger_middle
            if latest_close is not None and band_span > 0:
                bollinger_percent_b = (latest_close - bollinger_lower) / band_span

        sma_50 = _sma(closes, 50)
        sma_200 = _sma(closes, 200)
        return MarketIndicators(
            symbol=str(meta.get("symbol") or str(symbol or "").strip().upper()),
            currency=str(meta.get("currency") or ""),
            exchange=str(meta.get("exchangeName") or ""),
            interval=interval,
            range_window=range_window,
            close_count=_count_non_none(closes),
            latest_close=latest_close,
            period_high_52w=_highest(highs),
            period_low_52w=_lowest(lows),
            avg_volume_20=_sma(volumes, 20),
            vwap_session=_vwap(opens, highs, lows, closes, volumes),
            sma_10=_sma(closes, 10),
            sma_20=_sma(closes, 20),
            sma_50=sma_50,
            sma_100=_sma(closes, 100),
            sma_200=sma_200,
            ema_9=_last_non_none(ema_9_series),
            ema_12=_last_non_none(ema_12_series),
            ema_20=_last_non_none(ema_20_series),
            ema_26=_last_non_none(ema_26_series),
            ema_50=_last_non_none(ema_50_series),
            rsi_14=_rsi(closes, 14),
            macd=macd,
            macd_signal=macd_signal,
            macd_histogram=macd_histogram,
            bollinger_middle_20=bollinger_middle,
            bollinger_upper_20_2=bollinger_upper,
            bollinger_lower_20_2=bollinger_lower,
            bollinger_bandwidth=bollinger_bandwidth,
            bollinger_percent_b=bollinger_percent_b,
            atr_14=_atr(highs, lows, closes, 14),
            stochastic_k_14=_stochastic_k(highs, lows, closes, 14),
            stochastic_d_3=_stochastic_d(highs, lows, closes, 14, 3),
            adx_14=_adx(highs, lows, closes, 14),
            plus_di_14=_plus_di(highs, lows, closes, 14),
            minus_di_14=_minus_di(highs, lows, closes, 14),
            cci_20=_cci(highs, lows, closes, 20),
            williams_r_14=_williams_r(highs, lows, closes, 14),
            roc_12=_roc(closes, 12),
            momentum_10=_momentum(closes, 10),
            obv=_obv(closes, volumes),
            distance_to_sma_50_percent=_distance_percent(latest_close, sma_50),
            distance_to_sma_200_percent=_distance_percent(latest_close, sma_200),
        )

def _to_float(value: object) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None

def _count_non_none(values: list[float | None]) -> int:
    return sum(1 for value in values if value is not None)

def _last_non_none(values: list[float | None]) -> float | None:
    for value in reversed(values):
        if value is not None:
            return value
    return None

def _sma(values: list[float | None], period: int) -> float | None:
    window = _last_window(values, period)
    if window is None:
        return None
    return sum(window) / period

def _ema_series(values: list[float | None], period: int) -> list[float | None]:
    result: list[float | None] = []
    ema: float | None = None
    seed: list[float] = []
    multiplier = 2.0 / (period + 1.0)
    for value in values:
        if value is None:
            result.append(None)
            continue
        if ema is None:
            seed.append(value)
            if len(seed) < period:
                result.append(None)
                continue
            ema = sum(seed[-period:]) / period
            result.append(ema)
            continue
        ema = ((value - ema) * multiplier) + ema
        result.append(ema)
    return result

def _rsi(values: list[float | None], period: int) -> float | None:
    closes = _compact(values)
    if len(closes) <= period:
        return None
    gains: list[float] = []
    losses: list[float] = []
    for previous, current in zip(closes[:-1], closes[1:]):
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

def _bollinger_bands(values: list[float | None], period: int, stddev_multiplier: float) -> tuple[float | None, float | None, float | None]:
    window = _last_window(values, period)
    if window is None:
        return None, None, None
    mean = sum(window) / period
    variance = sum((value - mean) ** 2 for value in window) / period
    stddev = math.sqrt(variance)
    return mean, mean + (stddev_multiplier * stddev), mean - (stddev_multiplier * stddev)

def _true_ranges(highs: list[float | None], lows: list[float | None], closes: list[float | None]) -> list[float]:
    result: list[float] = []
    previous_close: float | None = None
    for high, low, close in zip(highs, lows, closes):
        if high is None or low is None:
            previous_close = close if close is not None else previous_close
            continue
        if previous_close is None:
            tr = high - low
        else:
            tr = max(high - low, abs(high - previous_close), abs(low - previous_close))
        result.append(tr)
        if close is not None:
            previous_close = close
    return result

def _atr(highs: list[float | None], lows: list[float | None], closes: list[float | None], period: int) -> float | None:
    true_ranges = _true_ranges(highs, lows, closes)
    return _wilder_average(true_ranges, period)

def _stochastic_k(highs: list[float | None], lows: list[float | None], closes: list[float | None], period: int) -> float | None:
    close = _last_non_none(closes)
    if close is None:
        return None
    high_window = _last_window(highs, period)
    low_window = _last_window(lows, period)
    if high_window is None or low_window is None:
        return None
    highest = max(high_window)
    lowest = min(low_window)
    span = highest - lowest
    if span == 0:
        return 0.0
    return ((close - lowest) / span) * 100.0

def _stochastic_d(highs: list[float | None], lows: list[float | None], closes: list[float | None], k_period: int, d_period: int) -> float | None:
    k_values: list[float] = []
    for index in range(len(closes)):
        k_value = _stochastic_k(highs[: index + 1], lows[: index + 1], closes[: index + 1], k_period)
        if k_value is not None:
            k_values.append(k_value)
    if len(k_values) < d_period:
        return None
    return sum(k_values[-d_period:]) / d_period

def _directional_movements(highs: list[float | None], lows: list[float | None]) -> tuple[list[float], list[float]]:
    plus_dm: list[float] = []
    minus_dm: list[float] = []
    previous_high: float | None = None
    previous_low: float | None = None
    for high, low in zip(highs, lows):
        if high is None or low is None or previous_high is None or previous_low is None:
            previous_high = high if high is not None else previous_high
            previous_low = low if low is not None else previous_low
            continue
        up_move = high - previous_high
        down_move = previous_low - low
        plus_dm.append(up_move if up_move > down_move and up_move > 0 else 0.0)
        minus_dm.append(down_move if down_move > up_move and down_move > 0 else 0.0)
        previous_high = high
        previous_low = low
    return plus_dm, minus_dm

def _plus_di(highs: list[float | None], lows: list[float | None], closes: list[float | None], period: int) -> float | None:
    plus_dm, _ = _directional_movements(highs, lows)
    atr = _atr(highs, lows, closes, period)
    plus_dm_avg = _wilder_average(plus_dm, period)
    if atr in (None, 0.0) or plus_dm_avg is None:
        return None
    return (plus_dm_avg / atr) * 100.0

def _minus_di(highs: list[float | None], lows: list[float | None], closes: list[float | None], period: int) -> float | None:
    _, minus_dm = _directional_movements(highs, lows)
    atr = _atr(highs, lows, closes, period)
    minus_dm_avg = _wilder_average(minus_dm, period)
    if atr in (None, 0.0) or minus_dm_avg is None:
        return None
    return (minus_dm_avg / atr) * 100.0

def _adx(highs: list[float | None], lows: list[float | None], closes: list[float | None], period: int) -> float | None:
    plus_dm, minus_dm = _directional_movements(highs, lows)
    tr_values = _true_ranges(highs, lows, closes)
    if len(tr_values) < period or len(plus_dm) < period or len(minus_dm) < period:
        return None
    atr_series = _wilder_average_series(tr_values, period)
    plus_series = _wilder_average_series(plus_dm, period)
    minus_series = _wilder_average_series(minus_dm, period)
    dx_values: list[float] = []
    for atr_value, plus_value, minus_value in zip(atr_series, plus_series, minus_series):
        if atr_value in (None, 0.0) or plus_value is None or minus_value is None:
            continue
        plus_di = (plus_value / atr_value) * 100.0
        minus_di = (minus_value / atr_value) * 100.0
        denom = plus_di + minus_di
        if denom == 0:
            dx_values.append(0.0)
        else:
            dx_values.append((abs(plus_di - minus_di) / denom) * 100.0)
    return _wilder_average(dx_values, period)

def _cci(highs: list[float | None], lows: list[float | None], closes: list[float | None], period: int) -> float | None:
    typical_prices: list[float] = []
    for high, low, close in zip(highs, lows, closes):
        if high is None or low is None or close is None:
            continue
        typical_prices.append((high + low + close) / 3.0)
    if len(typical_prices) < period:
        return None
    window = typical_prices[-period:]
    sma = sum(window) / period
    mean_deviation = sum(abs(value - sma) for value in window) / period
    if mean_deviation == 0:
        return 0.0
    return (window[-1] - sma) / (0.015 * mean_deviation)

def _williams_r(highs: list[float | None], lows: list[float | None], closes: list[float | None], period: int) -> float | None:
    close = _last_non_none(closes)
    if close is None:
        return None
    high_window = _last_window(highs, period)
    low_window = _last_window(lows, period)
    if high_window is None or low_window is None:
        return None
    highest = max(high_window)
    lowest = min(low_window)
    span = highest - lowest
    if span == 0:
        return 0.0
    return ((highest - close) / span) * -100.0

def _roc(values: list[float | None], period: int) -> float | None:
    compact = _compact(values)
    if len(compact) <= period:
        return None
    previous = compact[-period - 1]
    current = compact[-1]
    if previous == 0:
        return None
    return ((current - previous) / previous) * 100.0

def _momentum(values: list[float | None], period: int) -> float | None:
    compact = _compact(values)
    if len(compact) <= period:
        return None
    return compact[-1] - compact[-period - 1]

def _obv(closes: list[float | None], volumes: list[float | None]) -> float | None:
    obv = 0.0
    previous_close: float | None = None
    used = False
    for close, volume in zip(closes, volumes):
        if close is None or volume is None:
            continue
        if previous_close is None:
            previous_close = close
            used = True
            continue
        if close > previous_close:
            obv += volume
        elif close < previous_close:
            obv -= volume
        previous_close = close
        used = True
    return obv if used else None

def _vwap(
    opens: list[float | None],
    highs: list[float | None],
    lows: list[float | None],
    closes: list[float | None],
    volumes: list[float | None],
) -> float | None:
    numer = 0.0
    denom = 0.0
    for open_price, high, low, close, volume in zip(opens, highs, lows, closes, volumes):
        if high is None or low is None or close is None or volume is None:
            continue
        typical = (high + low + close) / 3.0
        numer += typical * volume
        denom += volume
    if denom == 0:
        return None
    return numer / denom

def _distance_percent(value: float | None, baseline: float | None) -> float | None:
    if value is None or baseline in (None, 0.0):
        return None
    return ((value - baseline) / baseline) * 100.0

def _highest(values: list[float | None]) -> float | None:
    compact = _compact(values)
    return max(compact) if compact else None

def _lowest(values: list[float | None]) -> float | None:
    compact = _compact(values)
    return min(compact) if compact else None

def _compact(values: list[float | None]) -> list[float]:
    return [value for value in values if value is not None]

def _last_window(values: list[float | None], period: int) -> list[float] | None:
    window = _compact(values[-period:])
    if len(window) != period:
        return None
    return window

def _pairwise_diff(left: list[float | None], right: list[float | None]) -> list[float | None]:
    result: list[float | None] = []
    for left_value, right_value in zip(left, right):
        if left_value is None or right_value is None:
            result.append(None)
        else:
            result.append(left_value - right_value)
    return result

def _wilder_average(values: list[float], period: int) -> float | None:
    series = _wilder_average_series(values, period)
    return _last_non_none(series)

def _wilder_average_series(values: list[float], period: int) -> list[float | None]:
    if len(values) < period:
        return []
    avg = sum(values[:period]) / period
    result: list[float | None] = [None] * (period - 1)
    result.append(avg)
    for value in values[period:]:
        avg = ((avg * (period - 1)) + value) / period
        result.append(avg)
    return result
