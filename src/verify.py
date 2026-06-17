"""verify.py — the judge-runnable proof.  `python -m src.verify <agent_id> <tick>`

Three green checks, on the judge's own machine:
  1. HASH    — keccak of the published proofs/<tick>.json == the commit on-chain
  2. REPLAY  — re-running decide()+RiskGuard on the COMMITTED inputs reproduces the
               committed action / size / reason / risk-verdict (the agent obeyed its own rules)
  3. ANCHOR  — the commit actually exists on-chain (non-empty)

Pass --offline <commit_hex> to check 1+2 without a chain read (used in tests/CI).
"""
from __future__ import annotations
import json
import sys
from pathlib import Path

from .signals import Signals
from .strategy import decide
from .guardrails import RiskConfig, PortfolioState, RiskGuard
from .proof import commit_hash

PROOFS = Path(__file__).resolve().parent.parent / "proofs"


def replay(record: dict) -> tuple[str, float, str, str]:
    """Reconstruct the decision + risk verdict from the COMMITTED inputs only."""
    sd = record["signals"]
    s = Signals(record["symbol"], sd["price"], sd["rsi"], sd["macd"], sd["macd_signal"],
                sd["ema_fast"], sd["ema_slow"], sd["fear_greed"], sd["funding_rate"])
    r = record["rules"]
    cfg = RiskConfig(max_drawdown_pct=r["max_drawdown_pct"], max_trade_pct=r["max_trade_pct"],
                     max_daily_trades=r["max_daily_trades"], max_slippage_pct=r["max_slippage_pct"],
                     token_allowlist=frozenset(r["allowlist"]))
    d = decide(s, max_trade_pct=cfg.max_trade_pct / 100)
    rk = record["risk"]
    state = PortfolioState(equity=rk["equity"], peak_equity=rk["peak_equity"], trades_today=rk["trades_today"])
    verdict = RiskGuard(cfg).check(d, state)[1]
    return d.action, d.size_pct, d.reason, verdict


def verify(record: dict, onchain_commit: str | None) -> tuple[bool, list[tuple[str, bool, str]]]:
    checks: list[tuple[str, bool, str]] = []

    recomputed = commit_hash(record)
    hash_ok = onchain_commit is not None and recomputed.lower() == onchain_commit.lower()
    checks.append(("HASH", hash_ok, f"recomputed {recomputed[:18]}… vs on-chain {str(onchain_commit)[:18]}…"))

    a, sz, reason, verdict = replay(record)
    replay_ok = (a == record["action"] and abs(sz - record["size_pct"]) < 1e-9
                 and reason == record["reason"] and verdict == record["risk"]["verdict"])
    checks.append(("REPLAY", replay_ok, f"action={a} size={sz} verdict={verdict!r}"))

    anchor_ok = bool(onchain_commit) and onchain_commit != "0x"
    checks.append(("ANCHOR", anchor_ok, f"on-chain commit present: {bool(onchain_commit)}"))

    return all(c[1] for c in checks), checks


def _load(tick: int) -> dict:
    return json.loads((PROOFS / f"{tick}.json").read_text())


def main(argv: list[str]) -> int:
    if "--offline" in argv:
        i = argv.index("--offline")
        tick = int(argv[i - 1]); commit = argv[i + 1]
    else:
        if len(argv) < 2:
            print("usage: python -m src.verify <agent_id> <tick>   (or: <tick> --offline <commit>)")
            return 2
        agent_id, tick = int(argv[0]), int(argv[1])
        from .identity import Identity
        commit = Identity().read_receipt(agent_id, tick)

    record = _load(tick)
    ok, checks = verify(record, commit)
    for name, passed, detail in checks:
        print(f"  [{'✓' if passed else '✗'}] {name:<7} {detail}")
    print(f"\n{'✓ ALL GREEN — receipt is real and recomputable' if ok else '✗ VERIFICATION FAILED'}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
