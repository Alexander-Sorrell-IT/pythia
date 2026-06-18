"""Triggered forwards — the CMC Agent Hub depth play.

A bare forward reads ONE CMC tool (narrative sectors). A *triggered* forward reads three and
commits them into the bet, so CMC consumption is load-bearing, not a free poll:

  1. trending_crypto_narratives  — the tradeable good (sector cap-share)        [narrative.py]
  2. get_global_crypto_derivatives_metrics — open-interest as the EARLY-TELL GATE: only author a
     forward when positioning is BUILDING (OI rising), not into a deleveraging tape.
  3. get_upcoming_macro_events  — anchor the horizon/evidence to a real macro event (date + url).

The whole trigger context is stored inside the forward's write_snapshot, so it keccak-hashes
into write_commit (nsr.write_commit_for) — tamper any reading and verify_pit's HASH check breaks.
Deterministic and recomputable; it does NOT touch settle() (the verdict math is unchanged).

  python -m src.trigger        # show the live gate decision + macro anchor
"""
from __future__ import annotations
import os
import re
import sys

from .narrative import mcp_call, parse_mcap


def parse_pct(s) -> float:
    """'+3.1%' -> 3.1 ; '-25.85%' -> -25.85 ; None -> 0.0."""
    if s is None:
        return 0.0
    m = re.search(r"-?[0-9.]+", str(s).replace(",", ""))
    return float(m.group(0)) if m else 0.0


def fetch_deriv(api_key: str) -> dict:
    d = mcp_call("get_global_crypto_derivatives_metrics", {}, api_key)
    oi = d.get("totalOpenInterest", {})
    return {"oi_usd": parse_mcap(oi.get("current")), "oi_change_24h_pct": parse_pct(oi.get("percentage_change_24h"))}


def fetch_macro(api_key: str) -> dict:
    d = mcp_call("get_upcoming_macro_events", {}, api_key)
    blk = d.get("upcomingEventNews", d)
    headers, rows = blk.get("headers", []), blk.get("rows", [])
    if not rows:
        return {"title": None, "event_date": None, "url": None}
    r = rows[0]
    pick = lambda col: r[headers.index(col)] if col in headers and headers.index(col) < len(r) else None
    return {"title": pick("title"), "event_date": pick("eventDate"), "url": pick("url")}


def build_trigger(api_key: str) -> dict:
    """The CMC trigger context: derivatives early-tell GATE + macro anchor. All committed into the forward."""
    deriv = fetch_deriv(api_key)
    macro = fetch_macro(api_key)
    gate_open = deriv["oi_change_24h_pct"] > 0    # positioning building -> author; deleveraging -> hold
    reason = (f"OI {deriv['oi_change_24h_pct']:+.2f}% 24h "
              f"({'building → author' if gate_open else 'deleveraging → hold'})")
    return {"deriv": deriv, "macro": macro, "gate_open": gate_open, "gate_reason": reason}


def main() -> int:
    try:
        from dotenv import load_dotenv; load_dotenv()
    except Exception:
        pass
    key = os.getenv("CMC_AGENT_HUB_KEY")
    if not key:
        print("CMC_AGENT_HUB_KEY not set — fill .env"); return 2
    t = build_trigger(key)
    G, R, D, B, Z = "\033[1;32m", "\033[1;31m", "\033[2m", "\033[1m", "\033[0m"
    print(f"\n{B}  CMC trigger — 3 tools committed into the forward{Z}\n")
    print(f"  derivatives  OI ${t['deriv']['oi_usd']/1e9:,.1f}B   24h {B}{t['deriv']['oi_change_24h_pct']:+.2f}%{Z}")
    g = t["gate_open"]
    print(f"  GATE         {(G+'OPEN') if g else (R+'CLOSED')}{Z}  —  {t['gate_reason']}")
    m = t["macro"]
    print(f"  macro anchor {m['title']}  ({m['event_date']})")
    print(f"  {D}{m['url']}{Z}")
    print(f"\n{D}  these readings hash into write_commit — tamper one and verify_pit's HASH breaks.{Z}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
