# DoraHacks BUIDL — ready-to-paste submission

Submit at: https://dorahacks.io/hackathon/bnbhack-twt-cmc/buidl
Deadline: **2026-06-21 07:00 UTC**. Track 2 has no on-chain registration — just submit here.

---

## Form fields

**BUIDL name**
Pythia

**Tagline / one-liner**
The first market where a forecasting agent's hindsight-proof on-chain track record IS its collateral and its price.

**Track**
Track 2 — Strategy Skills

**Specials targeted**
Best Use of CMC Agent Hub · Best Use of BNB AI Agent SDK

**GitHub link** (required)
https://github.com/Alexander-Sorrell-IT/pythia

**BNB Chain address** (the "BNB Chain" required field)
0xe2eE3d171191745B2C855BBe43A62283f5B69170
(ERC-8004 agent #1422, BNB Chain testnet — all writes gasless via MegaFuel paymaster)

**Demo video**
https://youtu.be/VPUbTMUXLR0

> NOTE: DoraHacks AND YouTube both reject `<` and `>` in text fields. The message below uses `→` instead of `->`. Do not paste any angle brackets anywhere.

**Cover image / thumbnail**
demo/pythia_thumbnail.png

---

## Message / description (paste into the BUIDL body)

Pythia is the first market where a forecasting agent's hindsight-proof on-chain track record IS its collateral and its price. Agents write narrative-rotation forwards on CoinMarketCap narrative-sector cap-share, settle them with no oracle — you re-derive the verdict yourself — and a settled record becomes the premium it quotes and the credit line it commands.

Run the whole claim on your own machine — you don't trust us, you verify us:

    git clone https://github.com/Alexander-Sorrell-IT/pythia && cd pythia && pip install -r requirements.txt
    python -m pytest tests/ -q              # 25 green
    python -m src.verify_pit 0001 --offline # re-derive a verdict yourself: HASH + REPLAY
    python -m src.credit                    # reputation → premium 50 / credit_line 500 (from 2/4 real proofs)
    python -m src.x402_pay                  # the payment rail refusing 3 live attacks
    python -m src.trigger                   # 3 CMC tools → the gate decision

With a funded testnet wallet, `python -m src.verify_pit 0001` reads two block timestamps off BNB Chain and prints FOUR GREEN — proving the verdict was committed before the data that settled it existed (ANCHOR-ORDER).

Best Use of CMC Agent Hub — three CMC tools, load-bearing (committed into the bet, so tampering breaks the four-green HASH): trending_crypto_narratives (the instrument — per-sector marketCapUsd, a settleable scalar no price feed exposes), get_global_crypto_derivatives_metrics (open-interest early-tell gate), get_upcoming_macro_events (macro anchor committed as evidence).

Best Use of BNB AI Agent SDK — ERC-8004 identity + on-chain reputation ledger (gasless), ERC-8183 escrow lifecycle for agent-to-agent credit, and x402 X402Signer wired into the credit loop (a Writer signs a quote, the Taker ecrecovers the payee and x402-pays that exact address, reputation-capped, with live refusals for redirect / overcharge / unbounded-Permit rug).

Limits, stated plainly: settlement is optimistic-dispute, not a deterministic oracle (the chain proves ordering and integrity). The 3-day demo plays both agents — a working slice, not a populated market. The 4 forwards settle against a short-horizon tape — a real distribution that proves the mechanism, not forecasting alpha. We never claim an on-chain oracle, a live market, or trading profit.

---

## Pre-submit checklist

- [x] Repo public & in sync (HEAD 12cb99c == origin/main)
- [x] 25 tests green; verify_pit / credit / x402_pay / trigger all run clean on live data
- [x] SUBMISSION.md test count corrected (23 -> 25)
- [x] Trailer final: demo/pythia_trailer.mp4 (64s, 720p, VO)
- [x] Thumbnail: demo/pythia_thumbnail.png (1280x720)
- [ ] Upload trailer (DoraHacks video upload, or unlisted YouTube) and paste link above
- [ ] Paste fields into the DoraHacks BUIDL form and submit before 2026-06-21 07:00 UTC
