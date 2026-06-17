"""Out-of-sample validation of the EXACT momentum long/flat rule.

Rule (verbatim from src/backtest.py momentum()):
    long (exposure=1) when  MACD > signal  AND  EMA7 > EMA30 ; else flat in cash.
Cost: 0.2% per side on every position change. Indicators computed on full history
then sliced per window so warmup (EMA/MACD seeding) is correct, not re-seeded each year.

Tests non-overlapping calendar-year windows 2021..2025 across BTC/ETH/BNB/SOL/XRP,
plus buy-hold for each window as the honest benchmark.
"""
from __future__ import annotations
import time, datetime as dt
import requests

BINANCE = "https://data-api.binance.vision/api/v3/klines"
COST = 0.002
ASSETS = ["BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT", "XRPUSDT"]
WARMUP = 35  # bars of indicator seeding before a window can trade


def fetch_all(symbol, start="2020-09-01", end="2026-01-01"):
    """Paginated daily klines -> list of (ts_ms, close)."""
    start_ms = int(dt.datetime.fromisoformat(start).replace(tzinfo=dt.timezone.utc).timestamp() * 1000)
    end_ms = int(dt.datetime.fromisoformat(end).replace(tzinfo=dt.timezone.utc).timestamp() * 1000)
    out = []
    cur = start_ms
    while cur < end_ms:
        r = requests.get(BINANCE, params={"symbol": symbol, "interval": "1d",
                                          "startTime": cur, "endTime": end_ms, "limit": 1000}, timeout=30)
        r.raise_for_status()
        chunk = r.json()
        if not chunk:
            break
        out.extend((int(k[0]), float(k[4])) for k in chunk)
        nxt = int(chunk[-1][0]) + 86400_000
        if nxt <= cur:
            break
        cur = nxt
        time.sleep(0.15)
    # dedupe by ts
    seen = {}
    for ts, c in out:
        seen[ts] = c
    return sorted(seen.items())


def ema(values, period):
    k = 2 / (period + 1)
    o = [values[0]]
    for v in values[1:]:
        o.append(v * k + o[-1] * (1 - k))
    return o


def macd_sig(values, fast=12, slow=26, sig=9):
    ef, es = ema(values, fast), ema(values, slow)
    m = [a - b for a, b in zip(ef, es)]
    return m, ema(m, sig)


def long_signal(closes):
    e7, e30 = ema(closes, 7), ema(closes, 30)
    m, s = macd_sig(closes)
    return [1.0 if (m[i] > s[i] and e7[i] > e30[i]) else 0.0 for i in range(len(closes))]


def simulate(closes, signal, lo, hi):
    """Trade indices [lo,hi). Position for day i's return is set by signal[i-1]
    (signal known only at the prior close -> no look-ahead).
    Returns (ret, maxdd, calmar, trades, exposure)."""
    equity, peak, maxdd = 1.0, 1.0, 0.0
    pos = 0.0
    trades, exp_sum, n = 0, 0.0, 0
    for i in range(lo, hi):
        target = signal[i - 1]
        if target != pos:
            equity *= (1 - COST)
            trades += 1
            pos = target
        r = closes[i] / closes[i - 1] - 1
        equity *= (1 + pos * r)
        peak = max(peak, equity)
        maxdd = max(maxdd, (peak - equity) / peak)
        exp_sum += pos
        n += 1
    ret = equity - 1
    cal = ret / maxdd if maxdd > 1e-9 else float("inf")
    return ret, maxdd, cal, trades, exp_sum / max(n, 1)


def buyhold(closes, lo, hi):
    equity, peak, maxdd = 1.0, 1.0, 0.0
    for i in range(lo, hi):
        r = closes[i] / closes[i - 1] - 1
        equity *= (1 + r)
        peak = max(peak, equity)
        maxdd = max(maxdd, (peak - equity) / peak)
    ret = equity - 1
    return ret, maxdd, (ret / maxdd if maxdd > 1e-9 else float("inf"))


def year_bounds(ts_list, year):
    y0 = int(dt.datetime(year, 1, 1, tzinfo=dt.timezone.utc).timestamp() * 1000)
    y1 = int(dt.datetime(year + 1, 1, 1, tzinfo=dt.timezone.utc).timestamp() * 1000)
    lo = next((i for i, t in enumerate(ts_list) if t >= y0), None)
    hi = next((i for i, t in enumerate(ts_list) if t >= y1), len(ts_list))
    return lo, hi


def main():
    data = {}
    for sym in ASSETS:
        rows = fetch_all(sym)
        data[sym] = rows
        print(f"# {sym}: {len(rows)} bars, {dt.datetime.utcfromtimestamp(rows[0][0]/1000).date()} -> {dt.datetime.utcfromtimestamp(rows[-1][0]/1000).date()}")
    print()

    years = [2021, 2022, 2023, 2024, 2025]
    # per (year, asset) momentum & buyhold
    agg = {y: {"mom": [], "bh": []} for y in years}
    print(f"{'asset':<8}{'year':>5} | {'MOM ret':>8}{'mDD':>7}{'cal':>6}{'tr':>4}{'exp':>5} | {'B&H ret':>8}{'mDD':>7}")
    for sym in ASSETS:
        rows = data[sym]
        ts = [r[0] for r in rows]
        closes = [r[1] for r in rows]
        sig = long_signal(closes)
        for y in years:
            lo, hi = year_bounds(ts, y)
            if lo is None or hi - lo < 60:
                continue
            lo = max(lo, WARMUP)  # ensure indicators seeded
            mret, mdd, mcal, mtr, mexp = simulate(closes, sig, lo, hi)
            bret, bdd, bcal = buyhold(closes, lo, hi)
            agg[y]["mom"].append((mret, mdd, mcal, mexp))
            agg[y]["bh"].append((bret, bdd))
            print(f"{sym:<8}{y:>5} | {mret*100:>7.1f}%{mdd*100:>6.1f}%{mcal:>6.2f}{mtr:>4}{mexp*100:>4.0f}% | {bret*100:>7.1f}%{bdd*100:>6.1f}%")
    print()
    print("== PER-YEAR AVERAGE ACROSS ASSETS (equal weight) ==")
    print(f"{'year':>5} | {'MOM avgRet':>10}{'avgDD':>7}{'avgCal':>7}{'avgExp':>7} | {'B&H avgRet':>10}{'avgDD':>7} | {'MOM beats B&H':>13}")
    for y in years:
        m = agg[y]["mom"]; b = agg[y]["bh"]
        if not m:
            continue
        mret = sum(x[0] for x in m)/len(m); mdd = sum(x[1] for x in m)/len(m)
        mcal = sum(x[2] for x in m)/len(m); mexp = sum(x[3] for x in m)/len(m)
        bret = sum(x[0] for x in b)/len(b); bdd = sum(x[1] for x in b)/len(b)
        wins = sum(1 for i in range(len(m)) if m[i][0] > b[i][0])
        print(f"{y:>5} | {mret*100:>9.1f}%{mdd*100:>6.1f}%{mcal:>7.2f}{mexp*100:>6.0f}% | {bret*100:>9.1f}%{bdd*100:>6.1f}% | {wins}/{len(m)}")

    # full-period 2021-2025 compounded per asset (single long backtest, the real OOS picture)
    print()
    print("== FULL 2021-01 -> 2025-12 (compounded, per asset) ==")
    print(f"{'asset':<8} | {'MOM ret':>9}{'mDD':>7}{'cal':>6}{'exp':>5} | {'B&H ret':>10}{'mDD':>7}")
    full_mom, full_bh = [], []
    for sym in ASSETS:
        rows = data[sym]; ts=[r[0] for r in rows]; closes=[r[1] for r in rows]
        sig = long_signal(closes)
        lo, _ = year_bounds(ts, 2021); lo = max(lo or WARMUP, WARMUP)
        _, hi = year_bounds(ts, 2025)
        mret, mdd, mcal, mtr, mexp = simulate(closes, sig, lo, hi)
        bret, bdd, bcal = buyhold(closes, lo, hi)
        full_mom.append((mret, mdd, mcal, mexp)); full_bh.append((bret, bdd))
        print(f"{sym:<8} | {mret*100:>8.1f}%{mdd*100:>6.1f}%{mcal:>6.2f}{mexp*100:>4.0f}% | {bret*100:>9.1f}%{bdd*100:>6.1f}%")
    mret=sum(x[0] for x in full_mom)/len(full_mom); mdd=sum(x[1] for x in full_mom)/len(full_mom)
    mcal=sum(x[2] for x in full_mom)/len(full_mom); mexp=sum(x[3] for x in full_mom)/len(full_mom)
    bret=sum(x[0] for x in full_bh)/len(full_bh); bdd=sum(x[1] for x in full_bh)/len(full_bh)
    print(f"{'AVG':<8} | {mret*100:>8.1f}%{mdd*100:>6.1f}%{mcal:>6.2f}{mexp*100:>4.0f}% | {bret*100:>9.1f}%{bdd*100:>6.1f}%")


if __name__ == "__main__":
    main()
