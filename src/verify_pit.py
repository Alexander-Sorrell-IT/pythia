"""verify_pit.py — the judge IS the oracle.   python -m src.verify_pit <id>

Four green, on the judge's own machine:
  1. HASH         — the published forward + snapshots keccak to the on-chain commits
  2. REPLAY       — re-run the deterministic settle() over the COMMITTED CMC snapshots ->
                    REALIZED/MISSED bit-for-bit (no oracle needed: a stranger reproduces it)
  3. ANCHOR-EXISTS— both commits live on-chain (write + settle), under pit/1/<id> on agent #1422
  4. ANCHOR-ORDER — the write block precedes the settle block, AND the settle block is at/after
                    emitted_at + horizon. The verdict was committed BEFORE the data that settled
                    it existed. A colluding Writer+Taker cannot back-date a block.

--offline checks 1+2 only (no chain), for CI / pre-funding.
"""
from __future__ import annotations
import json
import sys

from .narrative import NarrativeForward, settle as settle_fwd
from .nsr import PIT, AGENT_ID, _snap_in, write_commit_for, settle_commit_for


def verify(rec: dict, idn=None) -> tuple[bool, list[tuple[str, bool | None, str]]]:
    checks: list[tuple[str, bool | None, str]] = []
    forward, wsnap = rec["forward"], rec["write_snapshot"]
    esnap, verdict = rec.get("expiry_snapshot"), rec.get("verdict")

    # 1. HASH
    wc = write_commit_for(forward, wsnap)
    sc = settle_commit_for(rec["id"], esnap, verdict) if esnap is not None else None
    hash_ok = wc == rec["write_commit"] and (sc == rec.get("settle_commit"))
    checks.append(("HASH", hash_ok, f"write {wc[:14]}… / settle {str(sc)[:14]}… == published"))

    # 2. REPLAY — recompute the verdict from the committed snapshots
    fwd = NarrativeForward(**forward)
    realized, detail = settle_fwd(fwd, _snap_in(wsnap), _snap_in(esnap))
    replay_ok = ("REALIZED" if realized else "MISSED") == verdict
    checks.append(("REPLAY", replay_ok, f"recomputed {verdict} — {detail}"))

    if idn is None:
        checks.append(("ANCHOR-EXISTS", None, "skipped (--offline)"))
        checks.append(("ANCHOR-ORDER", None, "skipped (--offline)"))
        return all(c[1] for c in checks if c[1] is not None), checks

    # 3. ANCHOR-EXISTS — read the commits back off-chain
    on_w = idn.sdk.get_metadata(AGENT_ID, f"pit/1/{rec['id']}:w")
    on_s = idn.sdk.get_metadata(AGENT_ID, f"pit/1/{rec['id']}:s")
    anchor_ok = on_w == rec["write_commit"] and on_s == rec["settle_commit"]
    checks.append(("ANCHOR-EXISTS", anchor_ok, f"on-chain write/settle commits match"))

    # 4. ANCHOR-ORDER — read the two block timestamps straight off BNB Chain
    w3 = idn.sdk.web3
    try:   # BSC is PoA: its block extraData is longer than Ethereum's, so web3 needs this to read blocks
        from web3.middleware import ExtraDataToPOAMiddleware
        w3.middleware_onion.inject(ExtraDataToPOAMiddleware, layer=0)
    except Exception:
        pass
    wt = w3.eth.get_block(rec["write_block"]).timestamp
    st = w3.eth.get_block(rec["settle_block"]).timestamp
    order_ok = (wt < st) and (st >= forward["emitted_at"] + forward["horizon_s"])
    checks.append(("ANCHOR-ORDER", order_ok,
                   f"write_ts {wt} < settle_ts {st}; settle >= emitted+horizon "
                   f"({forward['emitted_at'] + forward['horizon_s']})"))

    return all(c[1] for c in checks if c[1] is not None), checks


def main(argv: list[str]) -> int:
    try:
        from dotenv import load_dotenv; load_dotenv()
    except Exception:
        pass
    offline = "--offline" in argv
    ids = [a for a in argv if not a.startswith("--")]
    if not ids:
        print("usage: python -m src.verify_pit <id> [--offline]"); return 2
    rec = json.loads((PIT / f"{ids[0]}.json").read_text())

    idn = None
    if not offline:
        from .identity import Identity
        idn = Identity(); idn.agent_id = AGENT_ID

    ok, checks = verify(rec, idn)
    for name, passed, detail in checks:
        mark = "•" if passed is None else ("✓" if passed else "✗")
        print(f"  [{mark}] {name:<13} {detail}")
    print(f"\n{'✓✓✓✓ FOUR GREEN — the verdict is real and you re-derived it' if ok else '✗ verification failed'}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
