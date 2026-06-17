"""Agent loop — wires DATA → BRAIN → GUARDRAILS → EXECUTION.

Default run is a dry-run over mock signals so you can see the full decision loop
without any credentials. Swap MockSignalProvider→CmcSignalProvider and
DryRunExecutor→TwakExecutor once keys are in .env.
"""
from __future__ import annotations

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

import os

from .signals import MockSignalProvider, CmcSignalProvider
from .strategy import decide
from .guardrails import RiskConfig, RiskGuard, PortfolioState
from .execution import DryRunExecutor

SYMBOLS = ["BNB", "ETH", "BTC"]
TICKS = 8


def make_provider():
    key = os.getenv("CMC_AGENT_HUB_KEY")
    if key:
        print("[signals] live CoinMarketCap Agent Hub")
        return CmcSignalProvider(key, os.getenv("CMC_MCP_URL", "https://mcp.coinmarketcap.com/mcp"))
    print("[signals] mock (no CMC_AGENT_HUB_KEY)")
    return MockSignalProvider()


def run() -> None:
    cfg = RiskConfig.from_env()
    provider = make_provider()
    guard = RiskGuard(cfg)
    executor = DryRunExecutor()
    state = PortfolioState(equity=1000.0, peak_equity=1000.0)

    print(f"== dry-run · {TICKS} ticks · equity ${state.equity:.0f} · drawdown cap {cfg.max_drawdown_pct}% ==\n")
    for t in range(1, TICKS + 1):
        for sym in SYMBOLS:
            s = provider.get(sym)
            d = decide(s, max_trade_pct=cfg.max_trade_pct / 100)
            approved, why = guard.check(d, state)
            if approved and d.action != "hold":
                fill = executor.execute(d, s.price, state.equity)
                if fill.action == "buy":
                    state.trades_today += 1
                tag = f"{fill.action.upper()} ${fill.notional:.0f} @ {fill.price}"
            else:
                tag = "HOLD" if d.action == "hold" else why
            print(f"t{t} {sym:<4} {d.action:<4} conf={d.confidence:.2f} | {tag}")
            print(f"        why: {d.reason}")
    print(f"\n== done · trades today: {state.trades_today} ==")


if __name__ == "__main__":
    run()
