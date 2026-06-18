"""NarrativePit — the one-command demo.

The agent forecaster credit market, end to end:

  1. live CoinMarketCap narrative read  — top sectors by cap-SHARE (fetch_snapshot)
  2. write a forward + anchor it on BNB Chain BEFORE the horizon         (do_write)
  3. let the horizon pass, settle + anchor the verdict on-chain AFTER     (do_settle)
  4. verify_pit FOUR GREEN — incl. ANCHOR-ORDER: the write block precedes the
     settle-data block, so a colluding Writer+Taker cannot back-date the call
  5. credit — the settled hit_rate IS the price (premium) and the collateral
     (credit_line); reputation-gated contrast: veteran #1422 vs low-record #1446
  6. a settled forecast becomes spendable.

HONEST: settlement is OPTIMISTIC-DISPUTE (a judge re-derives it from committed
public CMC snapshots — NOT a live on-chain oracle, NOT a populated market). For
the demo we play BOTH agents (a working slice). All on-chain writes are gasless
(MegaFuel paymaster).

Run live (needs CMC_AGENT_HUB_KEY + PRIVATE_KEY in .env):
    python demo/demo.py
Run offline (no keys, no chain — narrative read + settle + verify_pit):
    python demo/demo.py --offline
"""
from __future__ import annotations
import json
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
try:
    from dotenv import load_dotenv; load_dotenv()
except Exception:
    pass

from src.narrative import NarrativeForward, settle as settle_fwd
from src.nsr import PIT, AGENT_ID, _snap_in, do_write, do_settle
from src import verify_pit as VP
from src import credit as C

VETERAN_ID = AGENT_ID          # 1422 — full settled record
ROOKIE_ID = 1446               # a low-record forecaster, for the gated contrast
DEMO_HORIZON_S = 25            # short horizon so the live demo settles in one run

# ── ANSI ────────────────────────────────────────────────────────────────────
C_CYAN, C_GRN, C_RED, C_YEL = "\033[1;36m", "\033[1;32m", "\033[1;31m", "\033[1;33m"
C_WHT, C_DIM, C_BLD, C_RST = "\033[1;37m", "\033[2m", "\033[1m", "\033[0m"


def banner(t: str) -> None:
    print(f"\n{C_CYAN}{'─' * 68}{C_RST}")
    print(f"{C_CYAN}  {t}{C_RST}")
    print(f"{C_CYAN}{'─' * 68}{C_RST}")


def ok(t: str) -> None:  print(f"  {C_GRN}✓{C_RST} {t}")
def bad(t: str) -> None: print(f"  {C_RED}✗{C_RST} {t}")
def info(t: str) -> None: print(f"  {t}")
def dim(t: str) -> None: print(f"  {C_DIM}{t}{C_RST}")


def disclaimer() -> None:
    print(f"{C_DIM}  optimistic-dispute settlement (a judge re-derives it — not a live "
          f"on-chain oracle).{C_RST}")
    print(f"{C_DIM}  for the demo we play both agents — a working slice, not a populated "
          f"market.{C_RST}")


def show_snapshot(caps: dict, names: dict, sector: str | None = None, top: int = 5) -> None:
    """Render the narrative sectors ranked by cap-SHARE."""
    total = sum(caps.values()) or 1.0
    ranked = sorted(caps.items(), key=lambda kv: kv[1], reverse=True)[:top]
    for slug, cap in ranked:
        share = cap / total * 100
        mark = f"{C_YEL}◄ forward{C_RST}" if slug == sector else ""
        name = names.get(slug, slug)
        print(f"    {name[:30]:<30} {C_BLD}{share:6.2f}%{C_RST}  share   "
              f"(${cap/1e9:,.0f}B)  {mark}")


# ── OFFLINE PATH ──────────────────────────────────────────────────────────────
def run_offline() -> int:
    print(f"\n{C_WHT}   N A R R A T I V E   P I T   —   the agent forecaster credit market{C_RST}")
    print(f"{C_DIM}   (offline — committed snapshots, no live CMC call, no chain){C_RST}")

    proofs = sorted(PIT.glob("*.json"))
    if not proofs:
        bad("no committed proofs under proofs/pit/ — run live once to author one.")
        return 1
    # Pick the latest SETTLED proof: a write-only proof (no verdict/expiry_snapshot) —
    # e.g. an interrupted live run — would crash settle()/verify_pit below.
    settled = [p for p in proofs if json.loads(p.read_text()).get("verdict")]
    if not settled:
        bad("found write-only proofs but none settled yet — run live once to settle one,")
        bad("or `python -m src.nsr settle <id>` to settle an existing write.")
        return 1
    rec = json.loads(settled[-1].read_text())
    fwd_d = rec["forward"]
    wsnap, esnap = rec["write_snapshot"], rec["expiry_snapshot"]

    banner("1 · narrative read — sectors by cap-SHARE  (committed CMC snapshot)")
    show_snapshot(wsnap["caps"], wsnap["names"], sector=fwd_d["sector"])
    name = wsnap["names"].get(fwd_d["sector"], fwd_d["sector"])
    dim(f"snapshot ts={wsnap['ts']}  total narrative mcap "
        f"${sum(wsnap['caps'].values())/1e12:,.2f}T")

    banner("2 · the forward (committed, hash-anchored)")
    info(f"agent #{rec['agent_id']} forecast: {C_BLD}{name}{C_RST} share grows "
         f"{C_BLD}≥ {fwd_d['threshold_pct']}%{C_RST} within {fwd_d['horizon_s']}s")
    info(f"write_commit  {rec['write_commit']}")
    dim(f"write_block {rec.get('write_block')}  (anchored on BNB Chain in the live run)")

    banner("3 · settle — re-derive the verdict from the committed snapshots")
    fwd = NarrativeForward(**fwd_d)
    realized, detail = settle_fwd(fwd, _snap_in(wsnap), _snap_in(esnap))
    verdict = "REALIZED" if realized else "MISSED"
    (ok if realized else info)(f"{C_BLD}{verdict}{C_RST}  —  {detail}")
    dim("deterministic: any stranger recomputes this from public CMC data.")

    banner("4 · verify_pit — re-derive on the judge's own machine")
    passed, checks = VP.verify(rec, None)   # offline: HASH + REPLAY only
    for cname, p, det in checks:
        line = ok if p else (info if p is None else bad)
        line(f"{cname:<13} {det}")
    dim("ANCHOR-EXISTS / ANCHOR-ORDER need the chain — run live for FOUR GREEN.")
    print(f"  → {C_GRN}HASH + REPLAY green{C_RST} (the two on-chain checks light up live)"
          if passed else f"  → {C_RED}verification failed{C_RST}")

    banner("5 · credit — the settled record IS the price and the collateral")
    hr, realized_n, total_n = C.hit_rate_from_proofs()
    info(f"veteran #{VETERAN_ID}: {realized_n}/{total_n} settled realized  ->  "
         f"hit_rate {C_BLD}{hr:.2f}{C_RST}")
    info(f"   premium     = base*(1-hr) = {C_BLD}{C.premium(hr)}{C_RST}   "
         f"(better record -> tighter spread)")
    info(f"   credit_line = base*hr     = {C_BLD}{C.credit_line(hr)}{C_RST}   "
         f"(better record -> bigger escrow)")
    print()
    rookie_hr = 0.20
    info(f"reputation-gated contrast (the live run reads both off chain):")
    info(f"   veteran #{VETERAN_ID}  hr {hr:.2f}  ->  credit_line {C_GRN}{C.credit_line(hr)}{C_RST}")
    info(f"   rookie  #{ROOKIE_ID}  hr {rookie_hr:.2f}  ->  credit_line "
         f"{C_YEL}{C.credit_line(rookie_hr)}{C_RST}")
    dim(f"offline: rookie hr {rookie_hr:.2f} is illustrative; live reads it from chain.")
    dim("same instrument, different price and collateral — set by the on-chain record.")

    banner("6 · spendable")
    print(f"  {C_GRN}{C_BLD}a settled forecast becomes spendable.{C_RST}")
    print()
    disclaimer()
    print()
    return 0


# ── LIVE PATH ─────────────────────────────────────────────────────────────────
def run_live() -> int:
    key = os.getenv("CMC_AGENT_HUB_KEY")
    if not key:
        bad("CMC_AGENT_HUB_KEY not set — run with --offline, or fill .env.")
        return 2
    if not os.getenv("PRIVATE_KEY"):
        bad("PRIVATE_KEY not set — run with --offline, or fill .env.")
        return 2

    from src.identity import Identity
    from src.narrative import fetch_snapshot
    idn = Identity(); idn.agent_id = AGENT_ID

    print(f"\n{C_WHT}   N A R R A T I V E   P I T   —   the agent forecaster credit market{C_RST}")
    print(f"{C_DIM}   live on bsc-testnet · gasless (MegaFuel) · CoinMarketCap Agent Hub{C_RST}")

    banner("1 · live narrative read — sectors by cap-SHARE  (CoinMarketCap)")
    snap = fetch_snapshot(key, int(time.time()))
    if not snap.caps:
        bad("CMC returned no narrative sectors — try again, or run with --offline.")
        return 2
    # forecast the current top sector's share simply holds (threshold 0%) over a short horizon
    sector = max(snap.caps, key=lambda s: snap.caps[s])
    show_snapshot(snap.caps, snap.names, sector=sector)
    dim(f"snapshot ts={snap.ts}  total narrative mcap ${snap.total/1e12:,.2f}T")

    banner("2 · write the forward + anchor it ON-CHAIN  (before the horizon)")
    name = snap.names.get(sector, sector)
    info(f"agent #{AGENT_ID} forecast: {C_BLD}{name}{C_RST} share grows "
         f"{C_BLD}≥ 0.0%{C_RST} within {DEMO_HORIZON_S}s")
    fid = do_write(sector, 0.0, DEMO_HORIZON_S, key, idn)
    ok(f"forward {fid} written; the verdict-bearing commit is now on BNB Chain")

    banner(f"3 · let the {DEMO_HORIZON_S}s horizon pass, then settle + anchor ON-CHAIN (after)")
    rec = json.loads((PIT / f"{fid}.json").read_text())
    wait = max(0, rec["expires_at"] - int(time.time())) + 2
    for left in range(wait, 0, -1):
        print(f"\r  {C_DIM}settling in {left:2d}s …{C_RST}", end="", flush=True)
        time.sleep(1)
    print("\r" + " " * 30 + "\r", end="")
    do_settle(fid, key, idn)

    banner("4 · verify_pit — FOUR GREEN on the judge's own machine")
    rec = json.loads((PIT / f"{fid}.json").read_text())
    # ANCHOR-ORDER reads block timestamps off-chain; if an anchor returned no block
    # (paymaster hiccup) or RPC stalls, surface it instead of crashing the whole demo.
    if rec.get("write_block") is None or rec.get("settle_block") is None:
        bad("an on-chain anchor returned no block number — verify needs both blocks.")
        bad(f"   write_block={rec.get('write_block')}  settle_block={rec.get('settle_block')}")
        dim("re-run, or `python -m src.verify_pit {fid}` once the txs have mined.".format(fid=fid))
    else:
        try:
            passed, checks = VP.verify(rec, idn)
            for cname, p, det in checks:
                (ok if p else bad)(f"{cname:<13} {det}")
            if passed:
                print(f"  → {C_GRN}{C_BLD}✓✓✓✓ FOUR GREEN — the verdict is real and re-derived; "
                      f"the write block precedes the settle data.{C_RST}")
            else:
                print(f"  → {C_RED}verification failed{C_RST}")
        except Exception as e:
            bad(f"verify_pit could not reach chain: {e}")
            dim(f"the proof is committed — re-run `python -m src.verify_pit {fid}`.")

    banner("5 · credit — the settled record IS the price and the collateral")
    hr, realized_n, total_n = C.hit_rate_from_proofs()   # local: from the committed proofs
    try:
        blk = C.publish_hit_rate(idn, hr)
        pub = f"   (published @ block {blk}, gasless)"
    except Exception as e:
        pub = f"   ({C_YEL}publish skipped: {e}{C_RST})"
    info(f"veteran #{VETERAN_ID}: {realized_n}/{total_n} settled realized  ->  "
         f"hit_rate {C_BLD}{hr:.2f}{C_RST}{pub}")
    info(f"   premium     = base*(1-hr) = {C_BLD}{C.premium(hr)}{C_RST}")
    info(f"   credit_line = base*hr     = {C_BLD}{C.credit_line(hr)}{C_RST}")
    print()
    try:
        vet_hr = C.read_hit_rate(idn, VETERAN_ID)
        rookie_hr = C.read_hit_rate(idn, ROOKIE_ID)
        info("reputation-gated contrast (read straight off chain):")
        info(f"   veteran #{VETERAN_ID}  hr {vet_hr:.2f}  ->  credit_line "
             f"{C_GRN}{C.credit_line(vet_hr)}{C_RST}")
        info(f"   rookie  #{ROOKIE_ID}  hr {rookie_hr:.2f}  ->  credit_line "
             f"{C_YEL}{C.credit_line(rookie_hr)}{C_RST}")
        dim("same instrument, different price and collateral — set by the on-chain record.")
    except Exception as e:
        bad(f"could not read hit-rates off chain: {e}")
        dim("the contrast is reputation-gated — re-run once the RPC is reachable.")

    banner("6 · spendable")
    print(f"  {C_GRN}{C_BLD}a settled forecast becomes spendable.{C_RST}")
    print()
    disclaimer()
    print()
    return 0


def main(argv: list[str]) -> int:
    if "--offline" in argv:
        return run_offline()
    try:
        return run_live()
    except KeyboardInterrupt:
        print(f"\n{C_DIM}interrupted.{C_RST}")
        return 130


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
