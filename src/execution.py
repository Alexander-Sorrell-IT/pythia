"""Execution layer — the EXECUTION half of the loop.

`DryRunExecutor` simulates fills so the whole agent runs without keys or capital.
`TwakExecutor` is the real self-custody path: it shells out to the `twak` CLI
(Agent Wallet mode) so keys never leave the user — the heart of the TWAK award.
"""
from __future__ import annotations
from abc import ABC, abstractmethod
from dataclasses import dataclass
import subprocess

from .strategy import Decision


@dataclass
class Fill:
    symbol: str
    action: str
    notional: float
    price: float
    ok: bool
    detail: str


class Executor(ABC):
    @abstractmethod
    def execute(self, d: Decision, price: float, equity: float) -> Fill: ...


class DryRunExecutor(Executor):
    """Simulated fills at quoted price; no network, no keys."""

    def execute(self, d: Decision, price: float, equity: float) -> Fill:
        notional = equity * d.size_pct if d.action == "buy" else 0.0
        return Fill(d.symbol, d.action, round(notional, 2), price, True, "dry-run simulated fill")


class TwakExecutor(Executor):
    """Real execution via `twak` CLI (self-custody Agent Wallet). Needs TWAK creds + funded wallet."""

    def __init__(self, base_token: str = "USDT", quote_only: bool = True):
        self.base_token = base_token
        self.quote_only = quote_only  # safety: start in quote-only until we go live

    def execute(self, d: Decision, price: float, equity: float) -> Fill:
        if d.action == "hold":
            return Fill(d.symbol, "hold", 0.0, price, True, "no-op")
        notional = equity * d.size_pct if d.action == "buy" else 0.0
        amount = round(notional, 2)
        # buy SYMBOL with base_token; sell SYMBOL back to base_token
        if d.action == "buy":
            cmd = ["twak", "swap", str(amount), self.base_token, d.symbol]
        else:
            cmd = ["twak", "swap", "ALL", d.symbol, self.base_token]
        if self.quote_only:
            cmd.append("--quote-only")
        try:
            out = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
            ok = out.returncode == 0
            return Fill(d.symbol, d.action, amount, price, ok, (out.stdout or out.stderr).strip())
        except FileNotFoundError:
            return Fill(d.symbol, d.action, amount, price, False, "twak CLI not installed")
