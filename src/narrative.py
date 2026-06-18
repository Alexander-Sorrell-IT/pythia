"""NarrativePit — narrative-rotation forwards. The data + settlement moat.

CMC's trending_crypto_narratives publishes a per-SECTOR marketCapUsd — a settleable scalar
no generic price feed exposes. A narrative-rotation forward settles on the realized change in
a sector's SHARE of total narrative market-cap over a horizon. Deterministic and recomputable
from public CMC data — settle() is the heart the whole instrument stands on.
"""
from __future__ import annotations
from dataclasses import dataclass, field
import json
import os
import re
import subprocess

MCP_URL = os.getenv("CMC_MCP_URL", "https://mcp.coinmarketcap.com/mcp")
_UNITS = {"T": 1e12, "B": 1e9, "M": 1e6, "K": 1e3}


def parse_mcap(v) -> float:
    """'2.21 T' -> 2.21e12, '48.3 B' -> 4.83e10, None -> 0.0."""
    if v is None:
        return 0.0
    if isinstance(v, (int, float)):
        return float(v)
    m = re.match(r"\s*([0-9.]+)\s*([TBMK])?", str(v).replace(",", ""))
    if not m:
        return 0.0
    return float(m.group(1)) * _UNITS.get(m.group(2) or "", 1.0)


def mcp_call(name: str, arguments: dict, api_key: str):
    """CMC MCP via curl (requests/httpx hang on the SSE endpoint; curl returns in <1s)."""
    payload = json.dumps({"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                          "params": {"name": name, "arguments": arguments}})
    out = subprocess.run(
        ["curl", "-s", "--max-time", "30", "-X", "POST", MCP_URL,
         "-H", f"X-CMC-MCP-API-KEY: {api_key}", "-H", "Content-Type: application/json",
         "-H", "Accept: application/json, text/event-stream", "-d", payload],
        capture_output=True, text=True, timeout=40)
    m = re.search(r"\{.*\}", out.stdout, re.S)
    if not m:
        raise RuntimeError(f"CMC MCP {name}: {out.stdout[:160] or out.stderr[:160]}")
    return json.loads(json.loads(m.group(0))["result"]["content"][0]["text"])


@dataclass
class NarrativeSnapshot:
    caps: dict[str, float]                       # slug -> market cap (USD)
    names: dict[str, str] = field(default_factory=dict)   # slug -> display name
    ts: int = 0                                  # unix seconds

    @property
    def total(self) -> float:
        return sum(self.caps.values()) or 1.0

    def share(self, sector: str) -> float:       # sector = slug
        return self.caps.get(sector, 0.0) / self.total


def fetch_snapshot(api_key: str, ts: int) -> NarrativeSnapshot:
    data = mcp_call("trending_crypto_narratives", {}, api_key)
    cl = data.get("categoryList", data)
    headers, rows = cl["headers"], cl["rows"]
    si, ni, mi = headers.index("slug"), headers.index("categoryName"), headers.index("marketCapUsd")
    caps: dict[str, float] = {}
    names: dict[str, str] = {}
    for r in rows:
        slug = str(r[si]).strip()                # dedupe by STABLE slug, not display name
        caps[slug] = max(caps.get(slug, 0.0), parse_mcap(r[mi]))   # two rows, same slug -> one
        names[slug] = str(r[ni]).strip()
    return NarrativeSnapshot(caps=caps, names=names, ts=ts)


@dataclass
class NarrativeForward:
    sector: str
    threshold_pct: float      # required relative SHARE growth (e.g. 2.0 => sector's share rises >=2%)
    horizon_s: int
    emitted_at: int


def settle(fwd: NarrativeForward, snap_write: NarrativeSnapshot,
           snap_expiry: NarrativeSnapshot) -> tuple[bool, str]:
    """Deterministic: realized iff the sector's SHARE of total narrative mcap grew >= threshold%.

    Settles on a self-snapshotted cap-SHARE delta (drift-proof vs CMC's trailing % field).
    """
    s0, s1 = snap_write.share(fwd.sector), snap_expiry.share(fwd.sector)
    if s0 <= 0:
        return False, f"sector {fwd.sector!r} absent at write — void"
    growth = (s1 - s0) / s0 * 100
    realized = growth >= fwd.threshold_pct
    return realized, (f"share {s0*100:.3f}% -> {s1*100:.3f}%  "
                      f"({growth:+.2f}% vs +{fwd.threshold_pct}% needed)  => "
                      f"{'REALIZED' if realized else 'MISSED'}")
