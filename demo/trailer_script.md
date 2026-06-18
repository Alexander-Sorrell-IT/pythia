# Solvent — Trailer Script (58s)

VO = cloned voice (NeuTTS). On-screen = the real `demo/demo.py` terminal output, revealed live.
Rendered: `demo/solvent_trailer.mp4`.

| Time | VO (voiceover) | On screen |
|---|---|---|
| 0:00–0:09 | "Would you let a bot trade your money? Most AI trading agents are black boxes — they make a promise, and you just hope." | Title: **S O L V E N T — the accountable trading agent**. Section 1 banner: *live market read (CoinMarketCap Agent Hub)* — BNB price, RSI, MACD, Fear&Greed, the decision. |
| 0:09–0:19 | "Solvent is different. Before every trade, it writes its reasoning and its risk rules onto the blockchain. A receipt you can check." | Section 2: *commit the reason + risk receipt ON-CHAIN* — ERC-8004 agent **#1422**, the registration tx, the **receipt commit hash**, ✓ *public and immutable before it acts*. |
| 0:19–0:31 | "You don't trust it. You verify it. Clone the repo, run one command, and watch the agent's own decision recompute, exactly, against the chain." | Section 3: **VERIFY** — `HASH ✓  REPLAY ✓  ANCHOR ✓` → **ALL GREEN: the agent did exactly what it said**. |
| 0:31–0:43 | "And it doesn't stop at itself. Point Solvent's scanner at any agent on the network, and it catches the ones that signed a clean receipt for a trade their own rules forbid." | Section 4: **por.scan** — scanning a stranger (clean, valid hash) → **✗ FAIL: BUY DOGE violates its own rules — DOGE not in allowlist**. |
| 0:43–0:51 | "Built on BNB Chain. Powered by CoinMarketCap signals. Signed with Trust Wallet — so your keys never move." | Stack line: *BNB Chain · CoinMarketCap · Trust Wallet · self-custody*. |
| 0:51–0:58 | "Solvent is not built to gamble. It is built to be accountable by construction. An agent you don't have to trust — because you can check." | Closing card: **Not built to gamble. Built to be accountable by construction.** (hold + audio fade) |

## Notes
- Honest by design: **no profit/alpha claim anywhere** — the pitch is *accountability*, which is what's actually true and defensible.
- The on-screen content is the **real program** (`demo/demo.py`), not a mockup — live CMC data, real on-chain agent #1422, real recompute, real catch.
- Re-render VO at best fidelity: swap the NeuTTS backbone `q8-gguf` → `neutts-air` (full model, ~3.4 hr) and re-run `neutts_assemble.py`, then re-mux.
