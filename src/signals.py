"""Market signals — the DATA layer.

`Signals` is the contract the strategy brain consumes. Real data comes from the
CoinMarketCap Agent Hub (pre-computed RSI/MACD/EMA/Fear&Greed/funding); until we
have a key, `MockSignalProvider` produces the same shape so the rest of the agent
(strategy, guardrails, execution) is fully testable.
"""
from __future__ import annotations
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any
import json
import re
import random
import subprocess
import requests


@dataclass
class Signals:
    symbol: str
    price: float
    rsi: float            # 0-100
    macd: float
    macd_signal: float
    ema_fast: float
    ema_slow: float
    fear_greed: int       # 0-100 (0=extreme fear, 100=extreme greed)
    funding_rate: float   # perp funding, fraction (e.g. 0.0001)

    @property
    def macd_cross_up(self) -> bool:
        return self.macd > self.macd_signal

    @property
    def trend_up(self) -> bool:
        return self.ema_fast > self.ema_slow


class SignalProvider(ABC):
    @abstractmethod
    def get(self, symbol: str) -> Signals: ...


class MockSignalProvider(SignalProvider):
    """Deterministic-per-seed pseudo signals for dry-run + backtests."""

    def __init__(self, seed: int = 7):
        self._r = random.Random(seed)
        self._price = {"BNB": 620.0, "ETH": 2400.0, "BTC": 81000.0}

    def get(self, symbol: str) -> Signals:
        base = self._price.get(symbol, 1.0)
        drift = self._r.uniform(-0.03, 0.03)
        price = base * (1 + drift)
        self._price[symbol] = price
        return Signals(
            symbol=symbol,
            price=round(price, 4),
            rsi=round(self._r.uniform(20, 80), 1),
            macd=round(self._r.uniform(-2, 2), 3),
            macd_signal=round(self._r.uniform(-2, 2), 3),
            ema_fast=price * (1 + self._r.uniform(-0.01, 0.01)),
            ema_slow=price * (1 + self._r.uniform(-0.01, 0.01)),
            fear_greed=self._r.randint(10, 90),
            funding_rate=round(self._r.uniform(-0.0005, 0.0005), 6),
        )


# CoinMarketCap ids for the symbols we trade (extend as needed).
CMC_IDS = {"BTC": 1, "ETH": 1027, "BNB": 1839}
REST_BASE = "https://pro-api.coinmarketcap.com"


class CmcSignalProvider(SignalProvider):
    """Live CoinMarketCap Agent Hub adapter.

    Signals come from the Data MCP (technicals via `get_crypto_technical_analysis`,
    price via `get_crypto_quotes_latest`) plus the REST Fear & Greed endpoint.
    Fear & Greed is market-wide, so it's fetched once and cached per provider.
    """

    def __init__(self, api_key: str, mcp_url: str, ids: dict[str, int] | None = None):
        self.api_key = api_key
        self.mcp_url = mcp_url
        self.ids = ids or CMC_IDS
        self._fng: int | None = None

    def _mcp(self, name: str, arguments: dict) -> Any:
        # NOTE: the streaming MCP endpoint hangs `requests` and `httpx` (they wait on the
        # event-stream connection), but curl returns the full JSON in <1s. So we shell out.
        payload = json.dumps({"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                              "params": {"name": name, "arguments": arguments}})
        out = subprocess.run(
            ["curl", "-s", "--max-time", "30", "-X", "POST", self.mcp_url,
             "-H", f"X-CMC-MCP-API-KEY: {self.api_key}",
             "-H", "Content-Type: application/json",
             "-H", "Accept: application/json, text/event-stream",
             "-d", payload],
            capture_output=True, text=True, timeout=40,
        )
        body = out.stdout
        m = re.search(r"\{.*\}", body, re.S)  # handles plain JSON or SSE framing
        if not m:
            raise RuntimeError(f"CMC MCP {name}: unparseable response: {body[:200] or out.stderr[:200]}")
        env = json.loads(m.group(0))
        content = env.get("result", {}).get("content", [])
        if not content:
            raise RuntimeError(f"CMC MCP {name} returned no content: {body[:200]}")
        return json.loads(content[0]["text"])

    def _fear_greed(self) -> int:
        r = requests.get(f"{REST_BASE}/v3/fear-and-greed/latest", timeout=20,
                         headers={"X-CMC_PRO_API_KEY": self.api_key})
        r.raise_for_status()
        return int(r.json()["data"]["value"])

    def get(self, symbol: str) -> Signals:
        sym = symbol.upper()
        cid = self.ids.get(sym)
        if cid is None:
            raise ValueError(f"no CMC id for {sym}; add it to CMC_IDS")

        ta = self._mcp("get_crypto_technical_analysis", {"id": str(cid)})
        quote = self._mcp("get_crypto_quotes_latest", {"id": str(cid)})
        if self._fng is None:
            self._fng = self._fear_greed()

        ma, macd, rsi = ta["moving_averages"], ta["macd"], ta["rsi"]
        f = lambda v: float(str(v).replace(",", ""))   # CMC formats big numbers as "1,734.42"
        q = quote[0] if isinstance(quote, list) else quote
        return Signals(
            symbol=sym,
            price=round(f(q["price"]), 4),
            rsi=f(rsi["rsi14"]),
            macd=f(macd["macdLine"]),
            macd_signal=f(macd["signalLine"]),
            ema_fast=f(ma["exponential_moving_average_7_day"]),
            ema_slow=f(ma["exponential_moving_average_30_day"]),
            fear_greed=self._fng,
            funding_rate=0.0,   # populated from get_global_crypto_derivatives_metrics if needed
        )
