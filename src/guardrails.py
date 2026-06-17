"""Risk guardrails — every order passes through here before execution.

This is the module the "Best Use of TWAK" award rewards (autonomous execution
*within rules*) and the gate that keeps us under the Track 1 drawdown DQ threshold.
"""
from __future__ import annotations
from dataclasses import dataclass, field
import os

from .strategy import Decision


@dataclass
class RiskConfig:
    max_drawdown_pct: float = 25.0
    max_trade_pct: float = 20.0
    max_daily_trades: int = 12
    max_slippage_pct: float = 1.0
    token_allowlist: frozenset[str] = field(
        default_factory=lambda: frozenset({"BNB", "ETH", "BTC", "USDT", "USDC"})
    )

    @classmethod
    def from_env(cls) -> "RiskConfig":
        return cls(
            max_drawdown_pct=float(os.getenv("MAX_DRAWDOWN_PCT", 25)),
            max_trade_pct=float(os.getenv("MAX_TRADE_PCT", 20)),
            max_daily_trades=int(os.getenv("MAX_DAILY_TRADES", 12)),
            max_slippage_pct=float(os.getenv("MAX_SLIPPAGE_PCT", 1.0)),
        )


@dataclass
class PortfolioState:
    equity: float
    peak_equity: float
    trades_today: int = 0

    @property
    def drawdown_pct(self) -> float:
        if self.peak_equity <= 0:
            return 0.0
        return max(0.0, (self.peak_equity - self.equity) / self.peak_equity * 100)


class RiskGuard:
    def __init__(self, cfg: RiskConfig):
        self.cfg = cfg

    def check(self, d: Decision, state: PortfolioState) -> tuple[bool, str]:
        """Return (approved, reason). A blocked buy is downgraded to no-op upstream."""
        # Hard risk gate: at/over the drawdown cap, stop opening risk.
        if state.drawdown_pct >= self.cfg.max_drawdown_pct and d.action == "buy":
            return False, f"BLOCK: drawdown {state.drawdown_pct:.1f}% >= cap {self.cfg.max_drawdown_pct}%"

        if d.action == "buy":
            if d.symbol not in self.cfg.token_allowlist:
                return False, f"BLOCK: {d.symbol} not in allowlist"
            if state.trades_today >= self.cfg.max_daily_trades:
                return False, f"BLOCK: daily trade limit {self.cfg.max_daily_trades} reached"
            if d.size_pct * 100 > self.cfg.max_trade_pct:
                return False, f"BLOCK: size {d.size_pct*100:.1f}% > max {self.cfg.max_trade_pct}%"

        return True, "ok"
