"""Narrative Rotation Policy — the Track-2 backtestable CMC Skill.

A pure, deterministic policy over CMC narrative-sector cap-SHARE history:

  decide_rotation(snapshots) -> ranked sectors + a forward recommendation
  backtest(history)          -> per-sector hit-rate + a simple PnL

The policy is share-MOMENTUM: a sector whose SHARE of total narrative market-cap has been
rising is bet to keep rising. The recommendation is a NarrativeForward — the exact object the
clearing house writes and settles — so a thesis can be authored, anchored (src.nsr) and judged
(src.verify_pit) with no new settlement logic.

It is the Track-2 WEDGE because it is recomputable: backtest() replays narrative.settle() over
consecutive historical snapshots — the SAME function the on-chain forwards settle on — so anyone
can re-derive the per-sector hit-rate and PnL from the public snapshots. No private state, no
oracle, no look-ahead (each step decides on the prefix it would have seen live).

Honest: this is a SLICE, not a live market. Forwards settle by optimistic-dispute (see
src.verify_pit) — NOT a deterministic on-chain oracle — and in the demo both the maker and
taker agents are played by us. The backtest PnL is a settlement-replay scorecard, not a
tradeable return.
"""
from __future__ import annotations
from dataclasses import dataclass
import os
import time

from .narrative import (NarrativeSnapshot, NarrativeForward, fetch_snapshot,
                        settle as settle_fwd)

# Default forward terms the policy quotes around its top pick.
# threshold 0.0 => "share keeps rising"; realized iff growth >= 0% (the same bar settle() uses).
DEFAULT_THRESHOLD_PCT = 0.0
DEFAULT_HORIZON_S = 3600


@dataclass
class SectorRank:
    sector: str            # slug
    name: str
    share: float           # latest SHARE of total narrative mcap (0..1)
    momentum_pct: float    # relative SHARE growth across the window (%)


@dataclass
class Recommendation:
    ranked: list[SectorRank]
    forward: NarrativeForward | None   # the bet on the top mover; None if no history/signal
    note: str


def _common_sectors(snapshots: list[NarrativeSnapshot]) -> list[str]:
    """Sectors present (cap > 0) in EVERY snapshot — only these have a settleable share path."""
    if not snapshots:
        return []
    common = set(s for s, c in snapshots[0].caps.items() if c > 0)
    for snap in snapshots[1:]:
        common &= set(s for s, c in snap.caps.items() if c > 0)
    return sorted(common)


def rank_sectors(snapshots: list[NarrativeSnapshot]) -> list[SectorRank]:
    """Deterministic ranking by SHARE momentum from first to last snapshot.

    momentum = (share_last - share_first) / share_first * 100, the same relative cap-SHARE delta
    settle() scores on. Ties broken by latest share, then slug — fully reproducible.

    NOTE: callers must pass snapshots already ordered by ts (decide_rotation does this); this
    helper uses snapshots[0]/[-1] verbatim so an out-of-order list would mismeasure momentum.
    """
    if len(snapshots) < 2:
        return []
    first, last = snapshots[0], snapshots[-1]
    ranks: list[SectorRank] = []
    for sector in _common_sectors(snapshots):
        s0, s1 = first.share(sector), last.share(sector)
        mom = (s1 - s0) / s0 * 100 if s0 > 0 else 0.0   # s0 > 0 guaranteed by _common_sectors
        ranks.append(SectorRank(sector, last.names.get(sector, sector), s1, mom))
    ranks.sort(key=lambda r: (-r.momentum_pct, -r.share, r.sector))
    return ranks


def decide_rotation(snapshots: list[NarrativeSnapshot],
                    threshold_pct: float = DEFAULT_THRESHOLD_PCT,
                    horizon_s: int = DEFAULT_HORIZON_S) -> Recommendation:
    """Rank sectors by share-momentum and recommend a forward on the top mover.

    Pure function of the snapshots (sorted by ts internally for determinism). The forward is
    emitted at the LATEST snapshot's ts — the moment a live agent would author it.

    Self-consistency: the policy only stakes a sector whose observed momentum already clears the
    SAME bar settle() will judge the forward on (momentum_pct >= threshold_pct). It will not
    write a bet it can already see cannot clear its own threshold.
    """
    snaps = sorted(snapshots, key=lambda s: s.ts)
    ranks = rank_sectors(snaps)
    if not ranks:
        return Recommendation([], None, "insufficient history (need >=2 snapshots with shared sectors)")
    top = ranks[0]
    if top.momentum_pct < threshold_pct:
        return Recommendation(
            ranks, None,
            f"top mover {top.name} {top.momentum_pct:+.2f}% < +{threshold_pct}% bar — stand aside")
    forward = NarrativeForward(sector=top.sector, threshold_pct=threshold_pct,
                               horizon_s=horizon_s, emitted_at=snaps[-1].ts)
    note = (f"long {top.name} ({top.sector}): share {top.share*100:.3f}%, "
            f"momentum {top.momentum_pct:+.2f}% over last {len(snaps)} snapshots")
    return Recommendation(ranks, forward, note)


# ---------------------------------------------------------------------------
# Backtest: replay settle() over consecutive historical snapshots.
# ---------------------------------------------------------------------------

@dataclass
class SectorScore:
    sector: str
    name: str
    settled: int
    realized: int
    pnl: float

    @property
    def hit_rate(self) -> float:
        return self.realized / self.settled if self.settled else 0.0


@dataclass
class BacktestResult:
    per_sector: dict[str, SectorScore]
    settled: int
    realized: int
    pnl: float

    @property
    def hit_rate(self) -> float:
        return self.realized / self.settled if self.settled else 0.0


# Flat ±1-unit payoff: a REALIZED bet wins one stake, a MISSED bet loses one. Stake = 1 unit/bet
# so PnL reads as "net units (wins minus losses)". Deliberately simple — no market-impact,
# slippage or edge modeling — so the number is fully recomputable from the public snapshots.
# This is a settlement-replay scorecard, NOT a tradeable PnL claim.
STAKE = 1.0


def backtest(history: list[NarrativeSnapshot],
             window: int = 1,
             threshold_pct: float = DEFAULT_THRESHOLD_PCT) -> BacktestResult:
    """Replay the policy over a snapshot timeline and settle each call with narrative.settle().

    For each step i (window <= i < len-1): decide_rotation on the prefix snapshots[i-window .. i]
    (no look-ahead — only data available at i), author the forward at snapshot i, then settle it
    against snapshot i+1. Reuses narrative.settle so the verdicts equal the on-chain ones.

    `window` is the momentum lookback in snapshots; the core signature backtest(history) is
    unchanged (window=1 decides on the single prior step).
    """
    snaps = sorted(history, key=lambda s: s.ts)
    per: dict[str, SectorScore] = {}
    settled = realized = 0
    pnl = 0.0
    if window < 1:
        window = 1
    for i in range(window, len(snaps) - 1):
        prefix = snaps[i - window:i + 1]          # window+1 snapshots ending at the write snap
        # horizon_s is irrelevant to settle() (which scores on caps only) and this forward never
        # goes on-chain, so 0 is fine; threshold_pct mirrors the settlement bar.
        rec = decide_rotation(prefix, threshold_pct=threshold_pct, horizon_s=0)
        fwd = rec.forward
        if fwd is None:                            # policy stood aside this step
            continue
        write_snap, expiry_snap = snaps[i], snaps[i + 1]
        won, _detail = settle_fwd(fwd, write_snap, expiry_snap)
        sc = per.setdefault(fwd.sector,
                            SectorScore(fwd.sector, write_snap.names.get(fwd.sector, fwd.sector),
                                        0, 0, 0.0))
        sc.settled += 1
        settled += 1
        delta = STAKE if won else -STAKE
        sc.pnl += delta
        pnl += delta
        if won:
            sc.realized += 1
            realized += 1
    return BacktestResult(per, settled, realized, pnl)


def format_backtest(res: BacktestResult) -> str:
    lines = [f"{'sector':<28} {'settled':>7} {'realized':>8} {'hit':>6} {'pnl':>7}"]
    for sc in sorted(res.per_sector.values(), key=lambda s: (-s.hit_rate, -s.settled, s.sector)):
        lines.append(f"{sc.name[:28]:<28} {sc.settled:>7} {sc.realized:>8} "
                     f"{sc.hit_rate*100:>5.0f}% {sc.pnl:>+7.1f}")
    lines.append(f"{'TOTAL':<28} {res.settled:>7} {res.realized:>8} "
                 f"{res.hit_rate*100:>5.0f}% {res.pnl:>+7.1f}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# main(): fetch a few live snapshots, run the policy, print + reproducibility note.
# ---------------------------------------------------------------------------

def fetch_history(api_key: str, n: int = 3, gap_s: float = 8.0) -> list[NarrativeSnapshot]:
    """Pull n live snapshots gap_s apart (CMC's narrative caps move slowly; spacing yields signal).

    Timestamps are forced strictly increasing so the replayed timeline is monotonic — two fetches
    inside the same wall-clock second never collapse into a zero-elapsed (identical-ts) settle.
    """
    snaps: list[NarrativeSnapshot] = []
    last_ts = 0
    for k in range(n):
        if k:
            time.sleep(gap_s)
        snap = fetch_snapshot(api_key, int(time.time()))
        if snap.ts <= last_ts:                    # clock didn't advance — keep ts strictly rising
            snap.ts = last_ts + 1
        last_ts = snap.ts
        snaps.append(snap)
    return snaps


def main() -> None:
    try:
        from dotenv import load_dotenv; load_dotenv()
    except Exception:
        pass
    key = os.environ.get("CMC_AGENT_HUB_KEY")
    if not key:
        raise SystemExit("set CMC_AGENT_HUB_KEY (CMC Agent Hub MCP key) in env or .env")
    try:
        n = int(os.environ.get("SKILL_SNAPS", "3"))
    except ValueError:
        n = 3
    n = max(2, n)   # need >=2 snapshots to form any momentum / settle a bet

    print(f"== Narrative Rotation Policy · fetching {n} live snapshots ==")
    history = fetch_history(key, n)
    for s in history:
        print(f"  snapshot ts={s.ts}  sectors={len(s.caps)}  total=${s.total:,.0f}")

    rec = decide_rotation(history)
    print("\n-- ranking (by share momentum) --")
    print(f"{'#':>2} {'sector':<28} {'share':>8} {'momentum':>9}")
    for i, r in enumerate(rec.ranked[:8], 1):
        print(f"{i:>2} {r.name[:28]:<28} {r.share*100:>7.3f}% {r.momentum_pct:>+8.2f}%")

    print(f"\n-- recommendation --\n  {rec.note}")
    if rec.forward:
        f = rec.forward
        print(f"  forward: sector={f.sector} threshold=+{f.threshold_pct}% "
              f"horizon={f.horizon_s}s emitted_at={f.emitted_at}")
        print(f"  author + anchor on-chain:  python -m src.nsr write {f.sector} "
              f"{f.threshold_pct} {f.horizon_s}")

    res = backtest(history)
    print("\n-- backtest (replayed settle() over the fetched snapshots) --")
    print(format_backtest(res) if res.settled else "  (need more spaced snapshots to settle a bet)")

    print("\n-- reproducibility --")
    print("  deterministic: ranking + every verdict come from narrative.settle on the published")
    print("  cap-SHARE snapshots — no oracle, no look-ahead. Re-run on the SAME snapshots (the")
    print("  ones src.nsr anchors) and the hit-rate and PnL reproduce exactly. This is the same")
    print("  settlement src.verify_pit re-derives on-chain; settlement is optimistic-dispute, and")
    print("  in the demo both the maker and taker agents are played by us (a slice, not a market).")


if __name__ == "__main__":
    main()
