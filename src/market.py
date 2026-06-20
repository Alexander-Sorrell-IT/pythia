"""Integrated settlement — the negotiated quote pays itself.

Wires the three loose pieces into one flow (all gasless — local signing only):

  1. a Writer agent SIGNS a quote  {sector, premium = base·(1−hit_rate), writer, validBefore}
  2. the Taker RECOVERS the writer's address from the signature (ecrecover) — the payee is
     cryptographically bound to whoever signed the quote; tamper the quote and recovery yields a
     different address, so a redirected/forged quote cannot be paid
  3. the Taker pays that recovered address via x402 (X402Signer), capped by the writer's on-chain
     reputation (per-call = premium, session budget = credit_line), refusing redirect/overcharge/rug

This fuses x402 + reputation + the credit loop. The premium is priced by the writer's settled record;
the payee is provable; the payment is custody-safe. (Production uses the SDK's NegotiationHandler for
the quote; here we sign the quote directly with the agent wallet, which proves the same binding.)

  python -m src.market
"""
from __future__ import annotations
import json
import os
import sys
import time

from eth_account import Account
from eth_account.messages import encode_defunct

from .credit import premium
from .x402_pay import (make_signer, message as x402_message, domain, TRANSFER_TYPES, _sighex,
                       X402RecipientMismatchError)


def _quote_digest(quote: dict):
    return encode_defunct(text=json.dumps(quote, sort_keys=True, separators=(",", ":")))


def sign_quote(writer_key: str, sector: str, hit_rate: float) -> dict:
    """Writer signs a premium quote priced off its own reputation. Returns {quote, provider_sig}."""
    acct = Account.from_key(writer_key)
    quote = {"sector": sector, "premium": int(premium(hit_rate)), "hit_rate": hit_rate,
             "writer": acct.address, "valid_before": int(time.time()) + 300}
    sig = acct.sign_message(_quote_digest(quote))
    return {"quote": quote, "provider_sig": "0x" + sig.signature.hex().removeprefix("0x")}


def recover_writer(signed: dict) -> str:
    """ecrecover the address that signed the quote — the payee is whatever this returns."""
    return Account.recover_message(_quote_digest(signed["quote"]), signature=signed["provider_sig"])


def pay_quote(taker_idn, signed: dict) -> dict:
    """Recover the payee from the signed quote, then x402-pay the premium to exactly that address."""
    payee = recover_writer(signed)
    if payee.lower() != signed["quote"]["writer"].lower():
        raise X402RecipientMismatchError(
            f"recovered {payee} != quoted writer {signed['quote']['writer']} — quote forged/tampered")
    hr = signed["quote"]["hit_rate"]
    signer, prem, line = make_signer(taker_idn, hr)
    sig = signer.sign_payment(domain=domain(), types=TRANSFER_TYPES,
                              message=x402_message(taker_idn.wallet.address, payee, prem),
                              expected_to=payee)
    return {"payee": payee, "premium": prem, "credit_line": line, "sig": sig}


# ── demo ──────────────────────────────────────────────────────────────────────
C_G, C_R, C_C, C_D, C_B, C_0 = "\033[1;32m", "\033[1;31m", "\033[1;36m", "\033[2m", "\033[1m", "\033[0m"


def main() -> int:
    try:
        from dotenv import load_dotenv; load_dotenv()
    except Exception:
        pass
    if not os.getenv("PRIVATE_KEY"):
        print(f"{C_R}PRIVATE_KEY not set — fill .env{C_0}"); return 2
    from .identity import Identity
    from .credit import hit_rate_from_proofs
    idn = Identity()                       # the Taker (and, in this demo, also the Writer)
    hr, r, n = hit_rate_from_proofs()

    print(f"\n{C_B}  the negotiated quote pays itself — x402 + reputation, end to end{C_0}\n")
    signed = sign_quote(os.environ["PRIVATE_KEY"], "binance-ecosystem", hr)
    q = signed["quote"]
    print(f"  Writer signs a quote: premium {C_B}{q['premium']}{C_0} (priced off hit_rate {hr:.2f}, "
          f"{r}/{n} proofs)  → provider_sig {signed['provider_sig'][:16]}…")

    res = pay_quote(idn, signed)
    print(f"  Taker recovers payee from the signature → {C_G}{res['payee'][:12]}…{C_0} "
          f"(== the signing Writer)")
    print(f"  Taker x402-signs premium {res['premium']} to that recovered address "
          f"({_siglen_ok(res['sig'])}-byte sig), capped by credit_line {res['credit_line']}\n")

    # tamper beat — a forged quote (premium bumped) recovers a DIFFERENT signer → refused
    forged = json.loads(json.dumps(signed)); forged["quote"]["premium"] = 5
    try:
        pay_quote(idn, forged)
        print(f"  {C_R}✗ forged quote was NOT caught (bug){C_0}")
    except X402RecipientMismatchError:
        print(f"  {C_G}✓{C_0} FORGED QUOTE  premium tampered → recovery yields a different signer → "
              f"{C_B}refused{C_0}")
    print(f"\n{C_D}  the payee is provable, the price is the writer's record, the payment is "
          f"custody-safe — one flow.{C_0}\n")
    return 0


def _siglen_ok(sig: dict) -> int:
    h = _sighex(sig)
    return len(bytes.fromhex(h[2:])) if len(h) > 2 else 0


if __name__ == "__main__":
    sys.exit(main())
