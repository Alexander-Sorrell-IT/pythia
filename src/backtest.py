"""Backtest the candidate theses on real history and let the numbers pick the winner.

Single-asset long/flat vs USDT (matches the live design: rotate basket <-> stablecoin).
Scored on the competition's own yardstick: total return, MAX DRAWDOWN (DQ gate ~30%),
Calmar (return per unit drawdown), trade count, time-in-market.
"""
from __future__ import annotations
from dataclasses import dataclass

from .data import (Bar, fetch_klines, fetch_fng, attach_fng,
                   ema_series, rsi_series, macd_series)

ASSETS = ["BNBUSDT", "ETHUSDT", "BTCUSDT"]
DAYS = 365
COST = 0.002  # 0.2% per side: fee + slippage


@dataclass
class Series:
    closes: list[float]
    ema_f: list[float]
    ema_s: list[float]
    rsi: list[float]
    macd: list[float]
    sig: list[float]
    fng: list[int]


def build_series(bars: list[Bar]) -> Series:
    c = [b.close for b in bars]
    macd, sig = macd_series(c)
    return Series(c, ema_series(c, 7), ema_series(c, 30), rsi_series(c, 14),
                  macd, sig, [b.fng for b in bars])


# --- candidate theses: return target exposure in [0,1] for day i ---

def regime(s: Series, i: int) -> float:
    """Risk-on only when trend up AND not extreme greed AND not overbought; else stablecoin."""
    trend_up = s.ema_f[i] > s.ema_s[i]
    if trend_up and s.fng[i] < 78 and s.rsi[i] < 72:
        return 1.0
    return 0.0


def momentum(s: Series, i: int) -> float:
    return 1.0 if (s.macd[i] > s.sig[i] and s.ema_f[i] > s.ema_s[i]) else 0.0


def meanrev(s: Series, i: int) -> float:
    """Contrarian: buy fear/oversold, exit on greed/overbought (hysteresis via prior state handled in sim)."""
    if s.fng[i] < 30 or s.rsi[i] < 35:
        return 1.0
    if s.fng[i] > 70 or s.rsi[i] > 65:
        return 0.0
    return -1.0  # sentinel: hold previous position


def buyhold(s: Series, i: int) -> float:
    return 1.0


STRATS = {"regime": regime, "momentum": momentum, "meanrev": meanrev, "buyhold": buyhold}


@dataclass
class Result:
    ret: float
    max_dd: float
    calmar: float
    trades: int
    exposure: float


def simulate(s: Series, strat, warmup: int = 35) -> Result:
    equity = 1.0
    peak = 1.0
    max_dd = 0.0
    pos = 0.0          # current exposure 0..1
    trades = 0
    exp_sum = 0
    n = 0
    for i in range(warmup, len(s.closes)):
        # NO LOOK-AHEAD: decide on the PRIOR bar's close (i-1), then earn bar i's return.
        # (Deciding on strat(s, i) and earning closes[i]/closes[i-1] trades on info you
        #  don't have yet — it inflated returns ~50pts. This is the honest, tradeable form.)
        target = strat(s, i - 1)
        if target < 0:          # meanrev "hold" sentinel
            target = pos
        if target != pos:
            equity *= (1 - COST)  # rebalance cost
            trades += 1
            pos = target
        # next-bar return applied to the in-market fraction
        r = s.closes[i] / s.closes[i - 1] - 1
        equity *= (1 + pos * r)
        peak = max(peak, equity)
        max_dd = max(max_dd, (peak - equity) / peak)
        exp_sum += pos; n += 1
    return Result(equity - 1, max_dd, (equity - 1) / max_dd if max_dd > 1e-9 else float("inf"),
                  trades, exp_sum / max(n, 1))


def run() -> None:
    fng = fetch_fng(600)
    per_asset = {}
    for sym in ASSETS:
        bars = fetch_klines(sym, DAYS)
        attach_fng(bars, fng)
        per_asset[sym] = build_series(bars)

    print(f"== Backtest · {DAYS}d · {len(ASSETS)} assets · cost {COST*100:.1f}%/side ==\n")
    print(f"{'strategy':<10} {'avgRet':>8} {'maxDD':>7} {'calmar':>7} {'trades':>7} {'inMkt':>6}")
    rows = []
    for name, strat in STRATS.items():
        rs = [simulate(s, strat) for s in per_asset.values()]
        avg_ret = sum(r.ret for r in rs) / len(rs)
        worst_dd = max(r.max_dd for r in rs)
        avg_cal = sum((r.calmar if r.calmar != float("inf") else 0) for r in rs) / len(rs)
        avg_tr = sum(r.trades for r in rs) / len(rs)
        avg_exp = sum(r.exposure for r in rs) / len(rs)
        rows.append((name, avg_ret, worst_dd, avg_cal))
        print(f"{name:<10} {avg_ret*100:>7.1f}% {worst_dd*100:>6.1f}% {avg_cal:>7.2f} {avg_tr:>7.1f} {avg_exp*100:>5.0f}%")

    # winner = best Calmar among those that survive the DQ gate
    survivors = [r for r in rows if r[2] < 0.30]
    winner = max(survivors or rows, key=lambda r: r[3])
    print(f"\n>> winner (best return/drawdown under 30% DQ gate): {winner[0].upper()}")


if __name__ == "__main__":
    run()
