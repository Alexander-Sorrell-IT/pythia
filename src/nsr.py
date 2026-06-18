"""NarrativePit clearing house — write & settle narrative-rotation forwards, anchored on-chain.

  python -m src.nsr write <sector_slug> <threshold_pct> <horizon_s>   # author + anchor the verdict-bearing write
  python -m src.nsr settle <id>                                       # re-pull CMC, settle, anchor the result

Each forward's WRITE commit (the bet + the write-time snapshot) is anchored on BNB Chain BEFORE
the horizon; the SETTLE commit (expiry snapshot + verdict) is anchored after. verify_pit proves
the write block precedes the settle data block — no back-dating, no oracle. See verify_pit.py.
"""
from __future__ import annotations
import json
import os
import sys
import time
from pathlib import Path

from .narrative import fetch_snapshot, NarrativeSnapshot, NarrativeForward, settle as settle_fwd
from .proof import commit_hash

PIT = Path(__file__).resolve().parent.parent / "proofs" / "pit"
AGENT_ID = 1422


def _snap_out(s: NarrativeSnapshot) -> dict:
    return {"caps": s.caps, "names": s.names, "ts": s.ts}


def _snap_in(d: dict) -> NarrativeSnapshot:
    return NarrativeSnapshot(caps={k: float(v) for k, v in d["caps"].items()},
                             names=d.get("names", {}), ts=d["ts"])


def write_commit_for(forward: dict, write_snapshot: dict) -> str:
    return commit_hash({"forward": forward, "write_snapshot": write_snapshot})


def settle_commit_for(fid: str, expiry_snapshot: dict, verdict: str) -> str:
    return commit_hash({"id": fid, "expiry_snapshot": expiry_snapshot, "verdict": verdict})


def _anchor(idn, key: str, value: str) -> int | None:
    """set_metadata (gasless via MegaFuel) and return the block the commit landed in."""
    res = idn.sdk.set_metadata(AGENT_ID, key, value)
    blk = res.get("blockNumber")
    rcpt = res.get("receipt")
    if blk is None and rcpt is not None:
        blk = rcpt.get("blockNumber") if isinstance(rcpt, dict) else getattr(rcpt, "blockNumber", None)
    return blk


def do_write(sector: str, threshold_pct: float, horizon_s: int, key: str, idn=None) -> str:
    now = int(time.time())
    snap = fetch_snapshot(key, now)
    if sector not in snap.caps:
        raise SystemExit(f"sector slug {sector!r} not in current trending set: {sorted(snap.caps)[:8]}…")
    forward = {"sector": sector, "threshold_pct": threshold_pct, "horizon_s": horizon_s, "emitted_at": now}
    wsnap = _snap_out(snap)
    wcommit = write_commit_for(forward, wsnap)

    PIT.mkdir(parents=True, exist_ok=True)
    fid = f"{len(list(PIT.glob('*.json'))) + 1:04d}"
    wblock = _anchor(idn, f"pit/1/{fid}:w", wcommit) if idn else None
    (PIT / f"{fid}.json").write_text(json.dumps({
        "id": fid, "agent_id": AGENT_ID, "forward": forward,
        "write_snapshot": wsnap, "write_commit": wcommit, "write_block": wblock,
        "expires_at": now + horizon_s,
    }, indent=1))
    print(f"✓ wrote forward {fid}: {snap.names.get(sector, sector)} share +{threshold_pct}% in {horizon_s}s")
    print(f"  write_commit {wcommit}  block={wblock}  expires {now + horizon_s}")
    return fid


def do_settle(fid: str, key: str, idn=None) -> None:
    rec = json.loads((PIT / f"{fid}.json").read_text())
    fwd = NarrativeForward(**rec["forward"])
    wsnap = _snap_in(rec["write_snapshot"])
    esnap = fetch_snapshot(key, int(time.time()))
    realized, detail = settle_fwd(fwd, wsnap, esnap)
    verdict = "REALIZED" if realized else "MISSED"
    esnap_out = _snap_out(esnap)
    scommit = settle_commit_for(fid, esnap_out, verdict)
    eblock = _anchor(idn, f"pit/1/{fid}:s", scommit) if idn else None

    rec.update({"expiry_snapshot": esnap_out, "verdict": verdict, "settle_detail": detail,
                "settle_commit": scommit, "settle_block": eblock})
    (PIT / f"{fid}.json").write_text(json.dumps(rec, indent=1))
    print(f"✓ settled {fid}: {verdict}  ({detail})  block={eblock}")


def main(argv: list[str]) -> None:
    try:
        from dotenv import load_dotenv; load_dotenv()
    except Exception:
        pass
    key = os.environ["CMC_AGENT_HUB_KEY"]
    idn = None
    if "--dry" not in argv:
        from .identity import Identity
        idn = Identity(); idn.agent_id = AGENT_ID
    argv = [a for a in argv if a != "--dry"]

    if argv and argv[0] == "write":
        do_write(argv[1], float(argv[2]), int(argv[3]), key, idn)
    elif argv and argv[0] == "settle":
        do_settle(argv[1], key, idn)
    else:
        print("usage: python -m src.nsr write <slug> <threshold_pct> <horizon_s> | settle <id> [--dry]")


if __name__ == "__main__":
    main(sys.argv[1:])
