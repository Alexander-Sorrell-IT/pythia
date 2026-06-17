"""Historical data + indicators for backtesting (all from free, keyless sources).

Live signals come from CMC's pre-computed Agent Hub; for *backtesting* we need history,
so we pull Binance daily klines (free) and Fear & Greed history (alternative.me) and
compute the same indicators ourselves. This lets the data pick the strategy.
"""
from __future__ import annotations
from dataclasses import dataclass
import requests

# Binance's public data mirror — same payload, not geo-blocked like api.binance.com
BINANCE = "https://data-api.binance.vision/api/v3/klines"
FNG_HIST = "https://api.alternative.me/fng/"


@dataclass
class Bar:
    ts: int          # ms
    close: float
    fng: int = 50    # Fear & Greed for that day (filled from FNG history)


def fetch_klines(symbol_usdt: str, days: int = 400, interval: str = "1d") -> list[Bar]:
    r = requests.get(BINANCE, params={"symbol": symbol_usdt, "interval": interval, "limit": days}, timeout=30)
    r.raise_for_status()
    return [Bar(ts=int(k[0]), close=float(k[4])) for k in r.json()]


def fetch_fng(limit: int = 500) -> dict[int, int]:
    """Return {day_epoch_seconds_rounded_to_day: value}."""
    r = requests.get(FNG_HIST, params={"limit": limit, "format": "json"}, timeout=30)
    r.raise_for_status()
    out = {}
    for d in r.json()["data"]:
        day = int(d["timestamp"]) // 86400 * 86400
        out[day] = int(d["value"])
    return out


def attach_fng(bars: list[Bar], fng: dict[int, int]) -> None:
    last = 50
    for b in bars:
        day = (b.ts // 1000) // 86400 * 86400
        last = fng.get(day, last)
        b.fng = last


# --- pure indicator functions over a list of closes ---

def ema_series(values: list[float], period: int) -> list[float]:
    k = 2 / (period + 1)
    out = [values[0]]
    for v in values[1:]:
        out.append(v * k + out[-1] * (1 - k))
    return out


def rsi_series(values: list[float], period: int = 14) -> list[float]:
    out = [50.0] * len(values)
    gains, losses = 0.0, 0.0
    ag = al = 0.0
    for i in range(1, len(values)):
        ch = values[i] - values[i - 1]
        g, l = max(ch, 0.0), max(-ch, 0.0)
        if i <= period:
            gains += g; losses += l
            if i == period:
                ag, al = gains / period, losses / period
                out[i] = 100 - 100 / (1 + (ag / al if al else 999))
        else:
            ag = (ag * (period - 1) + g) / period
            al = (al * (period - 1) + l) / period
            out[i] = 100 - 100 / (1 + (ag / al if al else 999))
    return out


def macd_series(values: list[float], fast=12, slow=26, sig=9):
    ef, es = ema_series(values, fast), ema_series(values, slow)
    macd = [a - b for a, b in zip(ef, es)]
    signal = ema_series(macd, sig)
    return macd, signal
