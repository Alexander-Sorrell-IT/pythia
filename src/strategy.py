"""The STRATEGY BRAIN — signals in, a decision out.

Deterministic and explainable on purpose: every decision carries a `reason`, which
is what both the live agent (Track 1) and the backtestable CMC Skill (Track 2) need.
An optional LLM layer can sit on top later; the core stays auditable.
"""
from __future__ import annotations
from dataclasses import dataclass
from .signals import Signals


@dataclass
class Decision:
    action: str        # "buy" | "sell" | "hold"
    symbol: str
    size_pct: float    # fraction of portfolio to deploy on a buy (0-1)
    confidence: float  # 0-1
    reason: str


def decide(s: Signals, max_trade_pct: float = 0.20) -> Decision:
    """Blend momentum (MACD), trend (EMA), mean-reversion (RSI) and sentiment (Fear&Greed).

    Long bias when trend + momentum align and we're not buying into greed;
    exit when momentum rolls over or RSI is overbought.
    """
    bull = 0
    bear = 0
    notes = []

    # Momentum
    if s.macd_cross_up:
        bull += 1; notes.append("MACD>signal")
    else:
        bear += 1; notes.append("MACD<signal")

    # Trend
    if s.trend_up:
        bull += 1; notes.append("EMA trend up")
    else:
        bear += 1; notes.append("EMA trend down")

    # Mean reversion via RSI
    if s.rsi < 35:
        bull += 1; notes.append(f"RSI {s.rsi} oversold")
    elif s.rsi > 70:
        bear += 1; notes.append(f"RSI {s.rsi} overbought")

    # Sentiment: avoid buying extreme greed, lean in on fear
    if s.fear_greed < 30:
        bull += 1; notes.append(f"F&G {s.fear_greed} fear")
    elif s.fear_greed > 75:
        bear += 1; notes.append(f"F&G {s.fear_greed} greed")

    score = bull - bear
    confidence = min(1.0, abs(score) / 4)
    reason = "; ".join(notes)

    if score >= 2:
        return Decision("buy", s.symbol, round(max_trade_pct * confidence, 4), confidence, reason)
    if score <= -2:
        return Decision("sell", s.symbol, 0.0, confidence, reason)
    return Decision("hold", s.symbol, 0.0, confidence, reason)
