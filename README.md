# trading-agent (working name)

Crypto-native autonomous trading agent for **BNB Hack: AI Trading Agent Edition**
(BNB Chain × CoinMarketCap × Trust Wallet, $36k pool).

One agent, engineered to win **Track 1 placement + all 3 special prizes**, with its
strategy brain reusable as a **Track 2** CMC Skill.

## Architecture

```
        ┌─────────────────────────────────────────────┐
        │            STRATEGY BRAIN (strategy.py)       │  ← reused as Track 2 Skill
        │  signals → decision (buy/sell/hold + size)    │
        └───────────────┬───────────────┬───────────────┘
   signals.py           │               │   execution.py
   CMC Agent Hub:       ▼               ▼   TWAK (twak CLI, Agent Wallet):
   RSI/MACD/EMA,    ┌──────┐       ┌──────────┐  self-custody signing, swap on BSC
   Fear&Greed,      │ DATA │       │ EXECUTION│  guardrails.py gates every order
   funding, derivs  └──────┘       └──────────┘
        bnbagent (Python): ERC-8004 on-chain identity + X402Signer (x402 pay-per-call)
```

## Prize coverage (single build)
- **Track 1 PnL** — live trading Jun 22–28; `guardrails.py` keeps us under the drawdown DQ gate.
- **Best Use of TWAK** — Agent Wallet (autonomous), self-custody signing through the whole loop, x402, hard guardrails.
- **Best Use of Agent Hub** — decisions driven by CMC pre-computed signals + Skills routing.
- **Best Use of BNB SDK** — `bnbagent` ERC-8004 identity + x402 signer.
- **Track 2** — `strategy.py` packaged as a backtestable CMC Skill.

## Status
Scaffold runs end-to-end in **dry-run against mock signals**. Real adapters
(`CmcSignalProvider`, `TwakExecutor`) are stubbed pending API credentials — see `.env.example`.

## Run (dry-run)
```bash
pip install -r requirements.txt
python -m src.agent          # mock signals → strategy → guardrails → dry-run executor
```
