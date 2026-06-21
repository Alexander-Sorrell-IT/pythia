# Pythia — BNB Hack submission (Track 2 + specials)

**Repo:** https://github.com/Alexander-Sorrell-IT/pythia
**Track:** Track 2 — Strategy Skills · **Specials targeted:** Best Use of CMC Agent Hub, Best Use of BNB AI Agent SDK
**On-chain:** ERC-8004 agent **#1422** on BNB Chain testnet · all writes gasless via the MegaFuel paymaster

---

## One line

Pythia is the first market where a forecasting agent's **hindsight-proof on-chain track record IS its collateral and its price** — agents write narrative-rotation forwards on CoinMarketCap narrative-sector cap-share, settle them with *no oracle* (you re-derive the verdict yourself), and a settled record becomes the premium it quotes and the credit line it commands.

## The 30-second demo (judge runs it)

```bash
git clone https://github.com/Alexander-Sorrell-IT/pythia && cd pythia && pip install -r requirements.txt
python -m pytest tests/ -q          # 25 green
python -m src.verify_pit 0001 --offline   # re-derive a verdict yourself: HASH + REPLAY
python -m src.credit                # reputation → premium 50 / credit_line 500 (from 2/4 real proofs)
python -m src.x402_pay              # the payment rail refusing 3 live attacks
python -m src.trigger               # 3 CMC tools → the gate decision
```
With a funded testnet wallet, `python -m src.verify_pit 0001` reads two block timestamps off BNB Chain and prints **FOUR GREEN** — proving the verdict was committed *before* the data that settled it existed.

## How it scores the four panel criteria

- **Technical execution (real, not cosmetic).** Four-green `verify_pit` runs against *live BNB Chain blocks*: HASH (published JSON keccaks to the on-chain commit), REPLAY (the deterministic `settle()` reproduces the verdict bit-for-bit), ANCHOR-EXISTS, and **ANCHOR-ORDER** (write block precedes the settle-data block). 4 forwards anchored on-chain, reputation published on-chain, all gasless. 25 unit tests.
- **Originality.** A genuinely new category — *proof-as-collateral*. ANCHOR-ORDER makes a forecast record hindsight-proof, which is what lets a forecast become **bankable** with no oracle and no bank. Settlement and underwriting collapse into one on-chain act.
- **Real-world relevance.** The user is the capital allocator / fund-of-agents (Theoriq, Sherwood, Giza exist today) that routes money to stranger agents and needs a *trustless* way to price and gate them. Reputation-as-credit is that primitive.
- **Demo.** One command re-derives the whole claim on the judge's own machine — they don't trust us, they verify us.

## Best Use of CMC Agent Hub

Three CMC tools, **load-bearing** (committed into the bet, so tampering breaks the four-green HASH — not a free poll):
- `trending_crypto_narratives` — the instrument itself: per-sector `marketCapUsd`, a settleable scalar no generic price feed exposes.
- `get_global_crypto_derivatives_metrics` — open-interest as the **early-tell GATE** (author only when positioning is building).
- `get_upcoming_macro_events` — the **macro anchor** (date + url) committed as evidence.

## Best Use of BNB AI Agent SDK

Three SDK subsystems, all load-bearing:
- **ERC-8004** identity + on-chain **reputation ledger** (`set_metadata`/`get_metadata`) — the agent's earned record, gasless.
- **ERC-8183** escrow lifecycle implemented (`create_job`/`set_budget`/`fund`/`settle`/`dispute`, `src/escrow.py`) for agent-to-agent credit, budget capped by `credit_line`. *Honest: ERC-8183 is not MegaFuel-sponsored (unlike our ERC-8004 core), so the on-chain run is gas-pending on this testnet wallet; the lifecycle returns clean status dicts and a self-escrow fallback rather than faking a tx.*
- **x402 `X402Signer`** — custody-safe premium settlement, **wired into the credit loop**: a Writer signs a quote, the Taker `ecrecover`s the payee from the signature and x402-pays *that exact address* — the negotiated quote pays itself, reputation-priced (`credit_line` caps the spend), with live refusals for redirect / overcharge / unbounded-Permit rug, and a forged quote refused by recovery mismatch (`src/x402_pay.py` + `src/market.py`).

## Track 2 deliverable

`src/skill.py` — the narrative-rotation policy as a deterministic, backtestable, recomputable CMC Skill (same `settle()` core, reproducible on a fresh clone).

## We say the limits plainly

Settlement is **optimistic-dispute, not a deterministic oracle** (the chain proves *ordering and integrity*). The 3-day demo plays **both** agents (a working slice, not a populated market). The 4 forwards settle against a roughly static short-horizon tape — a real distribution that proves the **mechanism**, *not* forecasting alpha. We never claim an on-chain oracle, a live market, or trading profit.
