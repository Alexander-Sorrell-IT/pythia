"""Credit layer — a forecaster's settled, hindsight-proof record becomes its price AND collateral.

  hit_rate    = realized / settled forwards   (only ANCHOR-ORDER-verifiable verdicts count)
  premium     = base * (1 - hit_rate)         better record -> tighter spread it can quote
  credit_line = base * hit_rate               better record -> bigger escrow it can command

hit_rate is written on-chain under rep/1/hitrate (gasless via MegaFuel), so a Taker re-derives
the quote and the budget cap itself — reputation is the price and the collateral, on-chain.
"""
from __future__ import annotations
import json
import sys
from pathlib import Path

from .nsr import PIT, AGENT_ID, _anchor

REP_KEY = "rep/1/hitrate"
BASE_PREMIUM = 100.0      # quote units for a 0%-record forecaster
BASE_CREDIT = 1000.0      # max escrow a 100%-record forecaster can command


def hit_rate_from_proofs(proofs_dir: Path = PIT) -> tuple[float, int, int]:
    recs = [json.loads(p.read_text()) for p in Path(proofs_dir).glob("*.json")]
    settled = [r for r in recs if r.get("verdict")]
    if not settled:
        return 0.0, 0, 0
    realized = sum(1 for r in settled if r["verdict"] == "REALIZED")
    return realized / len(settled), realized, len(settled)


def premium(hit_rate: float, base: float = BASE_PREMIUM) -> float:
    return round(base * (1 - hit_rate), 2)


def credit_line(hit_rate: float, base: float = BASE_CREDIT) -> float:
    return round(base * hit_rate, 2)


def publish_hit_rate(idn, hit_rate: float) -> int | None:
    """Write the hit-rate on-chain (gasless). Returns the block it landed in."""
    return _anchor(idn, REP_KEY, f"{hit_rate:.6f}")


def read_hit_rate(idn, agent_id: int = AGENT_ID) -> float:
    v = idn.sdk.get_metadata(agent_id, REP_KEY)
    return float(v) if v and v != "0x" else 0.0


def main(argv: list[str]) -> None:
    try:
        from dotenv import load_dotenv; load_dotenv()
    except Exception:
        pass
    hr, realized, total = hit_rate_from_proofs()
    print(f"settled forwards: {total}  realized: {realized}  ->  hit_rate {hr:.3f}")
    print(f"  quote premium   = base*(1-hit_rate) = {premium(hr)}")
    print(f"  credit_line     = base*hit_rate     = {credit_line(hr)}")
    if "--publish" in argv:
        from .identity import Identity
        idn = Identity(); idn.agent_id = AGENT_ID
        blk = publish_hit_rate(idn, hr)
        print(f"  published hit_rate on-chain (rep/1/hitrate) @ block {blk}")
        print(f"  read back from chain: {read_hit_rate(idn)}")


if __name__ == "__main__":
    main(sys.argv[1:])
