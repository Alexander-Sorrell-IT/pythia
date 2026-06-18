# Solvent — the agent forecaster credit market

**Proven forecasts are the collateral. No oracle, no bank, no operator in the loop.**

Solvent (built on the **NarrativePit** core) is a credit and clearing layer for autonomous
forecasting agents. An agent writes a forward on a CoinMarketCap narrative-sector cap-*share*,
the verdict is committed on-chain *before* the data that settles it exists, and the agent's
settled, hindsight-proof track record becomes its **price** (the premium it can quote) and its
**collateral** (the credit line it can command). Reputation stops being a star rating and becomes
working capital.

This is a new category: **proof-as-collateral, self-clearing.** It could not exist before an
*anchor-order* verifier, because until a forecast could be proven settled before its settling data
existed, reputation was an unfalsifiable claim — and unfalsifiable claims can't back credit.

---

## What this is (and what it isn't)

- It **is** a working slice: one forecaster (agent **#1422**, live on BNB Chain testnet), one
  forward anchored on-chain with four-green proof, and reputation deriving a price and a credit line.
- It **is not** an on-chain oracle. Settlement is **optimistic-dispute**: anyone can re-derive the
  verdict from public CMC data and the on-chain commits, and a wrong verdict is disputable. The chain
  proves *ordering and integrity*, not truth-by-fiat.
- It **is not** a live, populated market. In the demo we play both sides (Writer and Taker), and the
  single anchored forward is a zero-delta smoke test, not a real directional win. See
  [Limitations](#limitations) — we say this plainly.

---

## Quickstart (judge-runnable)

```bash
git clone https://github.com/Alexander-Sorrell-IT/solvent
cd solvent
pip install -r requirements.txt   # needs `curl` on PATH for the live CMC read (steps 2/4)
```

The one anchored proof (`proofs/pit/0001.json`, agent **#1422**) ships in the repo, so step 1 runs
on a fresh clone with no keys and no chain.

### 1. Re-derive a verdict yourself — no chain, no keys

```bash
python -m src.verify_pit 0001 --offline
```

You recompute, on your own machine, that the published forward + snapshots keccak to the committed
hashes (**HASH**) and that the deterministic `settle()` reproduces the verdict bit-for-bit
(**REPLAY**). The two on-chain checks show as skipped offline:

```
  [✓] HASH          write 0x4d25aef54022… / settle 0x1b91b36c5ebc… == published
  [✓] REPLAY        recomputed REALIZED — share 30.303% -> 30.303%  (+0.00% vs +0.0% needed)  => REALIZED
  [•] ANCHOR-EXISTS skipped (--offline)
  [•] ANCHOR-ORDER  skipped (--offline)

  ✓✓✓✓ FOUR GREEN — the verdict is real and you re-derived it
```

> **Read this honestly:** offline, only **two** of the four checks actually run (HASH + REPLAY).
> The tool still prints its `FOUR GREEN` banner offline — that's the banner for the two integrity
> checks passing, **not** proof of the two on-chain checks. The on-chain half (ANCHOR-EXISTS,
> ANCHOR-ORDER) only runs in step 2, against a wallet. Don't take the offline banner as the full
> four-green.

### 2. See the full four-green (reads BNB Chain testnet)

```bash
cp .env.example .env     # fill a funded bsc-testnet PRIVATE_KEY (+ WALLET_PASSWORD if set); keep NETWORK=bsc-testnet
python -m src.verify_pit 0001
```

This step needs **only a funded testnet wallet** — it reads the chain, not CMC, so no Agent Hub key
is required here. With the wallet, **ANCHOR-EXISTS** reads both commits back off-chain and
**ANCHOR-ORDER** reads the two block timestamps straight from BNB Chain — proving the write block
precedes the settle-data block *and* the settle block is at/after `emitted_at + horizon`. The verdict
was locked **before** the data that settled it existed. A colluding Writer + Taker cannot back-date a
block.

```
✓✓✓✓ FOUR GREEN — the verdict is real and you re-derived it
```

### 3. See reputation become price and credit

```bash
python -m src.credit
```

Reads the settled `proofs/pit/*.json` records, derives the agent's hit-rate, and prints the quote
premium and the credit line it backs:

```
settled forwards: 1  realized: 1  ->  hit_rate 1.000
  quote premium   = base*(1-hit_rate) = 0.0
  credit_line     = base*hit_rate     = 1000.0
```

Add `--publish` to anchor the hit-rate on-chain under `rep/1/hitrate` (gasless) and read it back
(needs a funded wallet, as in step 2).

### 4. Narrated walkthrough

```bash
python demo/demo.py            # live: needs CMC_AGENT_HUB_KEY + a funded PRIVATE_KEY in .env
python demo/demo.py --offline  # no keys, no chain: narrative read + settle + verify_pit + credit
```

This is the NarrativePit credit loop end to end: live CMC narrative read → write a forward and anchor
it on-chain *before* the horizon → let the horizon pass, settle and anchor the verdict *after* →
`verify_pit` four-green → the settled hit-rate priced as premium and credit line.

> The demo's step 5 prints a reputation-gated **contrast** — veteran `#1422` (hit-rate 1.00, credit
> 1000) next to a rookie `#1446` (hit-rate 0.20, credit 200). The veteran's numbers are derived from
> the real anchored proof; the rookie's are **illustrative narration** to show the mechanism. There
> is no `#1446` proof or second on-chain agent in this repo. See [Limitations](#limitations).

---

## Architecture

```
   CMC trending_crypto_narratives        per-SECTOR marketCapUsd — a settleable scalar
   (narrative.py: fetch_snapshot)         no generic price feed exposes
                 │
                 ▼
   FORWARD  ──►  on a sector's SHARE of total narrative cap, over a horizon
   (NarrativeForward: sector, threshold_pct, horizon_s)
                 │
        write_commit anchored ON-CHAIN  (nsr.do_write → set_metadata, gasless)  ── BEFORE horizon
                 │
                 ▼  …horizon elapses…
   SETTLE  ───►  re-pull CMC, deterministic cap-SHARE delta vs threshold → REALIZED / MISSED
   (narrative.settle)        settle_commit anchored ON-CHAIN (nsr.do_settle)  ── AFTER horizon
                 │
                 ▼
   ANCHOR-ORDER  the judge re-derives: write_block.ts < settle_block.ts,
   (verify_pit)  and settle_block.ts ≥ emitted_at + horizon            → no back-dating, no oracle
                 │
                 ▼
   CREDIT  ────► hit_rate = realized / settled  →  premium = base·(1−hit_rate)
   (credit.py)                                     credit_line = base·hit_rate
                 │
        hit_rate anchored ON-CHAIN (rep/1/hitrate) — a Taker re-derives the quote
        and the budget cap itself. Reputation is the price AND the collateral, on-chain.
                 └──────────────► next forward re-priced, next credit line resized. Loop closes.
```

The pieces alone are inert — a forward is a bet, ERC-8004 metadata is a key-value store. The new
thing is the feedback loop: **forecast → proof → credit → bigger forecast**, with reputation flowing
as the unit of account.

### Module map

| Module | Role |
|---|---|
| `src/narrative.py` | CMC narrative feed (curl MCP transport) + the deterministic `settle()` — the data + settlement moat |
| `src/proof.py` | Canonical, float-safe keccak `commit_hash` — deterministic across dict reordering |
| `src/nsr.py` | The clearing house: `do_write` / `do_settle` — author, settle, and anchor forwards on-chain |
| `src/verify_pit.py` | The judge-runnable verifier: HASH / REPLAY / ANCHOR-EXISTS / **ANCHOR-ORDER** |
| `src/credit.py` | Settled record → on-chain `hit_rate` → premium + credit line |
| `src/identity.py` | ERC-8004 identity; `set_metadata` / `get_metadata` as the reputation ledger |
| `src/dex.py` | Self-custody PancakeSwap executor — optional Track-1 leg only |

---

## What's proven on-chain

- **Four-green, gasless.** Agent #1422's forward `0001` is anchored on BNB Chain testnet: both
  commits exist, the write block precedes the settle-data block, and the verdict re-derives from the
  committed CMC snapshots. All anchoring is gasless via the **MegaFuel** paymaster. (Forward `0001`
  is a `threshold_pct = 0.0` forward on `binance-ecosystem` whose write/expiry snapshots are equal —
  a +0.00% ≥ 0.0% smoke test that exercises the full anchor-and-re-derive rail, not a directional
  call. See [Limitations](#limitations).)
- **Reputation-gated credit.** The hit-rate is published on-chain under `rep/1/hitrate` and read
  back; the premium and credit line are recomputable by anyone from that single on-chain value.
  With a perfect record the agent's `credit_line` is **1000** and its `premium` is **0**; a poor
  record contracts the line and widens the spread — `credit_line = base·hit_rate`,
  `premium = base·(1−hit_rate)`.

---

## Prize map

This is a **Track 2** submission targeting the two cross-track specials it is genuinely eligible
for. *Best Use of TWAK is **Track-1-only** (a live-PnL trading agent), so it is out of scope here —
and this build uses the BNB SDK's `X402Signer`, not the Trust Wallet Agent Kit.*

- **Track 2 — Strategy Skills** — `skill.py`: the narrative-rotation policy as a deterministic,
  backtestable, recomputable CMC Skill (the same `settle()` core, reproducible on a fresh clone).
- **Best Use of BNB AI Agent SDK** *(both tracks)* — three SDK subsystems, all load-bearing:
  ERC-8004 identity + on-chain **reputation ledger** (`set_metadata`/`get_metadata`, MegaFuel-gasless);
  the **ERC-8183 escrow** rail (`create_job`/`set_budget`/`fund`/`settle`/`dispute`, `escrow.py`); and
  **x402 `X402Signer`** custody-safe premium settlement with three live anti-rug refusals
  (`x402_pay.py`).
- **Best Use of CMC Agent Hub** *(both tracks)* — three CMC tools committed into every forward:
  `trending_crypto_narratives` (the instrument — per-sector `marketCapUsd`, a scalar no price feed
  exposes), `get_global_crypto_derivatives_metrics` (the open-interest early-tell **gate**), and
  `get_upcoming_macro_events` (the macro **anchor**) — all hashed into `write_commit`, so tampering
  any reading breaks `verify_pit`'s HASH (`trigger.py`).

---

## Limitations

We'd rather you trust the parts that are real than oversell the rest.

- **Optimistic-dispute, not an oracle.** Solvent does not assert truth on-chain. It proves *ordering
  and integrity* — the verdict was committed before its settling data existed — and lets anyone
  re-derive the result from public CMC data. A wrong verdict is disputable, not impossible. We never
  claim a deterministic on-chain oracle.
- **One forward, and it's a smoke test.** The single anchored proof (`0001`) is a zero-threshold
  forward whose write and expiry snapshots are identical, so it realizes trivially. It proves the
  *rail* — write → anchor → horizon → settle → anchor → four-green re-derivation — end to end. It is
  not evidence of forecasting skill, and the hit-rate of 1.000 reflects one degenerate sample.
- **A slice, not a populated market.** The 3-day demo runs **both** agents — we play the Writer and
  the Taker. It shows one forecaster, one credit line, one closed loop. It is the device turning on,
  not a live market with independent counterparties. The veteran-vs-rookie credit comparison
  (`#1422` vs `#1446`) is illustrative of the mechanism — the rookie figures are hardcoded narration,
  not a measured second agent.
- **Instrument demand is unproven.** We've shown the rail works end-to-end; we have **not** shown
  that agents *want* to trade narrative-rotation forwards at scale. Counterparty demand, liquidity,
  and adversarial behavior in a real market are open questions.
- **Testnet + faucet-gated.** Everything runs on BNB Chain testnet. The only thing between the
  offline-verifiable slice and a live on-chain anchor is gas/faucet funding for the agent wallet.

---

## Setup

```bash
pip install -r requirements.txt
cp .env.example .env
```

`.env.example` covers several layers; for the Solvent quickstart you need:

- `PRIVATE_KEY` — a dedicated, funded bsc-testnet wallet (never your main wallet), plus
  `WALLET_PASSWORD` if your key store is encrypted, and `NETWORK=bsc-testnet`.
- `CMC_AGENT_HUB_KEY` — CoinMarketCap Agent Hub, needed only when you re-pull live narrative data
  (`nsr` write/settle and the live `demo/demo.py`). It is **not** needed for `verify_pit` or
  `credit`, which replay committed snapshots.

`.env` is gitignored. Steps 1 and 3 of the quickstart run offline; step 2, `credit --publish`, and the
live demo require the chain (and `curl` on PATH for the CMC read).
