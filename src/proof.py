"""Canonical reason+risk receipt — the foundation of the on-chain moat.

Every fill serializes a canonical record of WHY it traded and that it obeyed its own rules,
hashes it (keccak256), and commits the hash on-chain (ERC-8004 set_metadata) BEFORE the swap.
A judge later recomputes the same hash from the published JSON and re-runs the rules — so the
serialization MUST be deterministic. Floats are the determinism trap, so every number is
formatted to a fixed-precision string before hashing. Verified stable across dict reordering.
"""
from __future__ import annotations
import json
from typing import Any

from eth_utils import keccak

from .signals import Signals
from .strategy import Decision
from .guardrails import RiskConfig, PortfolioState


def _canon(v: Any) -> Any:
    """Make a value deterministic: floats -> fixed-precision strings, recursively."""
    if isinstance(v, bool):
        return v
    if isinstance(v, float):
        return f"{v:.8f}"
    if isinstance(v, dict):
        return {k: _canon(v[k]) for k in v}
    if isinstance(v, (list, tuple)):
        return [_canon(x) for x in v]
    return v


def build_record(tick: int, agent_id: str, s: Signals, d: Decision,
                 cfg: RiskConfig, state: PortfolioState, verdict: str,
                 git_commit: str) -> dict:
    """The full reason+risk record. Commits the RULES AS DATA so a stranger can replay them."""
    return {
        "tick": tick,
        "agent_id": agent_id,
        "git_commit": git_commit,
        "symbol": s.symbol,
        # the exact signal vector the decision was made on
        "signals": {
            "price": s.price, "rsi": s.rsi, "macd": s.macd, "macd_signal": s.macd_signal,
            "ema_fast": s.ema_fast, "ema_slow": s.ema_slow,
            "fear_greed": s.fear_greed, "funding_rate": s.funding_rate,
        },
        # the decision
        "action": d.action, "size_pct": d.size_pct,
        "confidence": d.confidence, "reason": d.reason,
        # the risk state + the rules-as-data (so por.scan can replay them)
        "risk": {
            "drawdown_pct": state.drawdown_pct, "equity": state.equity,
            "peak_equity": state.peak_equity, "trades_today": state.trades_today,
            "verdict": verdict,
        },
        "rules": {
            "max_drawdown_pct": cfg.max_drawdown_pct, "max_trade_pct": cfg.max_trade_pct,
            "max_daily_trades": cfg.max_daily_trades, "max_slippage_pct": cfg.max_slippage_pct,
            "allowlist": sorted(cfg.token_allowlist),
        },
    }


def canonical_json(record: dict) -> str:
    """Deterministic serialization: canonicalized values, sorted keys, no whitespace."""
    return json.dumps(_canon(record), sort_keys=True, separators=(",", ":"))


def commit_hash(record: dict) -> str:
    """keccak256 of the canonical JSON, as a 0x-prefixed hex string (the on-chain value)."""
    return "0x" + keccak(text=canonical_json(record)).hex()
