"""Solvent — the one-command demo (and the trailer's on-screen footage).

Runs the REAL pieces: a live CoinMarketCap signal, a canonical on-chain receipt, the
3-green recompute, and por.scan catching a stranger agent that signed a clean receipt for
a trade its own rules forbid. Prints a clean, paced narrative. Run:  python demo/demo.py
"""
from __future__ import annotations
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
try:
    from dotenv import load_dotenv; load_dotenv()
except Exception:
    pass

from src.signals import Signals, CmcSignalProvider
from src.strategy import decide, Decision
from src.guardrails import RiskConfig, PortfolioState, RiskGuard
from src.proof import build_record, commit_hash
from src import verify as V
from src.por_scan import scan

AGENT_ID = 1422   # registered live on bsc-testnet
REG_TX = "0x5e349bc50100e166eba2e92fec98aeda68111dc445802c498dc5d58e1c09b062"


def banner(t): print(f"\n\033[1;36m== {t} ==\033[0m")
def ok(t): print(f"  \033[1;32m✓\033[0m {t}")
def bad(t): print(f"  \033[1;31m✗\033[0m {t}")


def live_signal() -> Signals:
    key = os.getenv("CMC_AGENT_HUB_KEY")
    if key:
        try:
            return CmcSignalProvider(key, os.getenv("CMC_MCP_URL", "https://mcp.coinmarketcap.com/mcp")).get("BNB")
        except Exception:
            pass
    return Signals("BNB", 604.55, 44.24, -10.94, -11.55, 608.2, 623.8, 24, 0.0)


def main():
    print("\033[1;37m\n   S O L V E N T  —  the accountable trading agent\033[0m")
    cfg = RiskConfig()

    banner("1 · live market read (CoinMarketCap Agent Hub)")
    s = live_signal()
    print(f"  BNB  ${s.price}   RSI14={s.rsi}   MACD={s.macd}/{s.macd_signal}   Fear&Greed={s.fear_greed}")
    d = decide(s, max_trade_pct=cfg.max_trade_pct / 100)
    print(f"  decision: \033[1m{d.action.upper()}\033[0m   ({d.reason})")

    banner("2 · commit the reason + risk receipt ON-CHAIN (before the trade)")
    state = PortfolioState(1000.0, 1000.0)
    verdict = RiskGuard(cfg).check(d, state)[1]
    rec = build_record(3, str(AGENT_ID), s, d, cfg, state, verdict, "75a5fdd")
    commit = commit_hash(rec)
    print(f"  ERC-8004 agent #{AGENT_ID}   (registered: {REG_TX[:22]}…)")
    print(f"  receipt commit  {commit}")
    ok("the agent's reasoning is now public and immutable — before it acts")

    banner("3 · VERIFY — recompute the agent's own decision (run it yourself)")
    passed, checks = V.verify(rec, commit)
    for name, p, detail in checks:
        (ok if p else bad)(f"{name:<7} {detail}")
    print(f"  → {'ALL GREEN: the agent did exactly what it said' if passed else 'FAILED'}")

    banner("4 · por.scan — catch a STRANGER agent lying about its own rules")
    sd = Signals("DOGE", 0.15, 30.0, 0.001, 0.0005, 0.16, 0.15, 24, 0.0)
    liar = build_record(7, "0x9b…f00d", sd, Decision("buy", "DOGE", 0.2, 1.0, "pump it"),
                        cfg, state, "ok", "75a5fdd")
    lc = commit_hash(liar)
    print("  scanning agent 0x9b…f00d  (it posted a CLEAN, valid hash)")
    v, why = scan(liar, lc)
    bad(f"{v}: {why}")
    print("  \033[2m(a clean hash that commit-reveal would wave through — caught by replaying its own rules)\033[0m")

    print("\n\033[1;37m   Not built to gamble. Built to be accountable by construction.\033[0m")
    print("   \033[2mBNB Chain · CoinMarketCap · Trust Wallet · self-custody\033[0m\n")


if __name__ == "__main__":
    main()
