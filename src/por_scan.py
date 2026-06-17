"""por.scan — the EYE.  `python -m src.por_scan --agent-id <id> --tick <n>`

Read-only verifier that adjudicates ANY agent's on-chain receipt using ONLY its committed
data — no foreign code. For a stranger agent it answers one question commit-reveal cannot:
**did the committed action actually obey the agent's own committed risk-rules?**

Verdicts:
  PASS     — hash matches the on-chain commit AND the committed action satisfies the
             committed rules (replayed through that agent's own RiskGuard rule-set).
  FAIL     — hash matches (so it's not a typo — they MEANT it) but the committed action
             violates the agent's OWN committed rules (e.g. a BUY of an off-allowlist token,
             or while over its own drawdown cap). The clean-hash-but-incoherent commit.
  TAMPERED — published JSON does not hash to the on-chain commit.
  UNSIGNED — no commit on-chain for that tick.

This is the capability Ananse / plain commit-reveal structurally cannot have: they only prove
a log is self-consistent; por.scan proves the log obeyed the rules it claims to run under.
"""
from __future__ import annotations
import json
import sys
from pathlib import Path

from .strategy import Decision
from .guardrails import RiskConfig, PortfolioState, RiskGuard
from .proof import commit_hash

PROOFS = Path(__file__).resolve().parent.parent / "proofs"


def scan(record: dict, onchain_commit: str | None) -> tuple[str, str]:
    """Return (verdict, reason) using only the committed record + the on-chain commit."""
    if not onchain_commit or onchain_commit == "0x":
        return "UNSIGNED", "no commit found on-chain for this tick"

    if commit_hash(record).lower() != onchain_commit.lower():
        return "TAMPERED", "published JSON does not hash to the on-chain commit"

    # Replay the agent's OWN committed rules against its OWN committed decision.
    r = record["rules"]
    cfg = RiskConfig(max_drawdown_pct=r["max_drawdown_pct"], max_trade_pct=r["max_trade_pct"],
                     max_daily_trades=r["max_daily_trades"], max_slippage_pct=r["max_slippage_pct"],
                     token_allowlist=frozenset(r["allowlist"]))
    committed = Decision(record["action"], record["symbol"], record["size_pct"],
                         record["confidence"], record["reason"])
    rk = record["risk"]
    state = PortfolioState(equity=rk["equity"], peak_equity=rk["peak_equity"], trades_today=rk["trades_today"])

    approved, why = RiskGuard(cfg).check(committed, state)
    if not approved:
        return "FAIL", f"committed {committed.action.upper()} {committed.symbol} violates its own rules — {why}"
    return "PASS", "committed action obeys its own committed rules"


def _load(agent_id: int, tick: int) -> dict | None:
    for p in (PROOFS / str(agent_id) / f"{tick}.json", PROOFS / f"{tick}.json"):
        if p.exists():
            return json.loads(p.read_text())
    return None


def main(argv: list[str]) -> int:
    args = {argv[i]: argv[i + 1] for i in range(0, len(argv) - 1, 2)}
    tick = int(args.get("--tick", "0"))

    if "--record" in args:                       # offline mode
        record = json.loads(Path(args["--record"]).read_text())
        commit = args.get("--commit")
    else:
        agent_id = int(args["--agent-id"])
        record = _load(agent_id, tick)
        if record is None:
            print(f"  [UNSIGNED] agent {agent_id} tick {tick}: no published record"); return 1
        from .identity import Identity
        commit = Identity().read_receipt(agent_id, tick)

    verdict, reason = scan(record, commit)
    mark = {"PASS": "✓", "FAIL": "✗", "TAMPERED": "✗", "UNSIGNED": "•"}[verdict]
    print(f"  [{mark}] {verdict:<8} tick {tick}: {reason}")
    return 0 if verdict == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
