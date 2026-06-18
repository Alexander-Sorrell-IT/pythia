"""x402 settlement — the Taker PAYS the Writer the premium, custody-safe.

The credit market priced forecasts (premium = base·(1−hit_rate)) but never *charged* for them.
This is the missing settlement edge: a Taker signs an EIP-3009 payment to the Writer through
bnbagent's X402Signer — gasless to SIGN — with three guards that make the agent's money moves
un-rug-pullable, every cap derived from the writer's ON-CHAIN reputation:

  * payee pinned byte-equal (expected_to)              → X402RecipientMismatchError on redirect
  * per-call value capped at the quoted premium        → X402AmountExceededError on overcharge
  * cumulative spend capped at the writer's credit_line → X402BudgetExhaustedError
  * the wallet's SigningPolicy refuses unbounded Permit / non-U-token domains → X402PolicyError

HONEST: the SDK SIGNS the authorization gaslessly; the payee / facilitator BROADCASTS it, and the
value is redeemed via escrow.fund() against the same U-token. We never claim the signer sends it.

  python -m src.x402_pay        # demo: one clean signed premium + three live refusals
"""
from __future__ import annotations
import os
import sys
import time

from bnbagent import X402Signer
from bnbagent.x402 import (X402RecipientMismatchError, X402AmountExceededError,
                           X402BudgetExhaustedError, X402PolicyError)
from bnbagent.networks import (PAYMENT_TOKEN_EIP712_NAME, PAYMENT_TOKEN_EIP712_VERSION,
                               get_address)

from .credit import premium, credit_line

CHAIN_ID = 97
TOKEN = get_address(CHAIN_ID).payment_token        # United Stables U-token (EIP-3009 verifyingContract)

# EIP-3009 TransferWithAuthorization — the only payment type the wallet's strict SigningPolicy allows.
TRANSFER_TYPES = {
    "TransferWithAuthorization": [
        {"name": "from", "type": "address"}, {"name": "to", "type": "address"},
        {"name": "value", "type": "uint256"}, {"name": "validAfter", "type": "uint256"},
        {"name": "validBefore", "type": "uint256"}, {"name": "nonce", "type": "bytes32"},
    ]
}


def domain(verifying: str = TOKEN) -> dict:
    return {"name": PAYMENT_TOKEN_EIP712_NAME, "version": PAYMENT_TOKEN_EIP712_VERSION,
            "chainId": CHAIN_ID, "verifyingContract": verifying}


def message(frm: str, to: str, value: int, ttl: int = 300) -> dict:
    now = int(time.time())
    return {"from": frm, "to": to, "value": int(value),
            "validAfter": now - 1, "validBefore": now + min(ttl, 300),
            "nonce": "0x" + os.urandom(32).hex()}


def make_signer(idn, hit_rate: float) -> tuple[X402Signer, int, int]:
    """Per-call cap = the quoted premium; session budget = the writer's credit_line. Both reputation-derived."""
    prem, line = int(premium(hit_rate)), int(credit_line(hit_rate))
    signer = X402Signer(idn.wallet, max_value_per_call={TOKEN: max(prem, 1)},
                        session_budget={TOKEN: max(line, 1)})
    return signer, prem, line


def pay_premium(idn, payee: str, hit_rate: float) -> dict:
    """Sign the EIP-3009 premium payment to the writer (payee). Returns the signature dict."""
    signer, prem, _ = make_signer(idn, hit_rate)
    return signer.sign_payment(domain=domain(), types=TRANSFER_TYPES,
                               message=message(idn.wallet.address, payee, prem), expected_to=payee)


# ── demo ──────────────────────────────────────────────────────────────────────
C_G, C_R, C_C, C_D, C_B, C_0 = "\033[1;32m", "\033[1;31m", "\033[1;36m", "\033[2m", "\033[1m", "\033[0m"


def _sighex(sig: dict) -> str:
    s = sig.get("signature", "")
    if isinstance(s, (bytes, bytearray)):
        s = s.hex()
    elif not isinstance(s, str) and hasattr(s, "hex"):   # HexBytes
        s = s.hex()
    return str(s) if str(s).startswith("0x") else "0x" + str(s)


def _siglen(sig: dict) -> int:
    h = _sighex(sig)
    return len(bytes.fromhex(h[2:])) if len(h) > 2 else 0


def main() -> int:
    try:
        from dotenv import load_dotenv; load_dotenv()
    except Exception:
        pass
    if not os.getenv("PRIVATE_KEY"):
        print(f"{C_R}PRIVATE_KEY not set — fill .env{C_0}"); return 2
    from .identity import Identity
    idn = Identity()
    me = idn.wallet.address

    hr = 0.5                                              # a mid-record forecaster → a real, non-zero premium
    writer = "0x1111111111111111111111111111111111111111"   # would be ecrecover(negotiation_hash, provider_sig)
    attacker = "0x2222222222222222222222222222222222222222"

    signer, prem, line = make_signer(idn, hr)
    print(f"\n{C_B}  x402 SETTLEMENT — the Taker pays the Writer, reputation-capped{C_0}")
    print(f"{C_D}  token {TOKEN} (United Stables, chain 97); signed gasless, broadcast by the payee.{C_0}\n")
    print(f"  writer hit_rate {C_B}{hr}{C_0}  →  premium {C_B}{prem}{C_0} (per-call cap)   "
          f"credit_line {C_B}{line}{C_0} (session budget)\n")

    sig = signer.sign_payment(domain=domain(), types=TRANSFER_TYPES,
                              message=message(me, writer, prem), expected_to=writer)
    print(f"  {C_G}✓ SIGNED{C_0} premium {prem} → {writer[:10]}…  "
          f"({_siglen(sig)}-byte sig {_sighex(sig)[:18]}…)")
    print(f"    {C_D}session budget remaining: {signer.budget.remaining(TOKEN) if hasattr(signer.budget,'remaining') else line-prem}{C_0}\n")

    print(f"{C_C}  three live refusals — the agent's money is un-rug-pullable:{C_0}")
    # 1 — redirected payee
    try:
        signer.sign_payment(domain=domain(), types=TRANSFER_TYPES,
                            message=message(me, attacker, prem), expected_to=writer)
        print(f"  {C_R}✗ redirect was NOT refused (bug){C_0}")
    except X402RecipientMismatchError:
        print(f"  {C_G}✓{C_0} REDIRECT  payee swapped to attacker → {C_B}refused{C_0} (X402RecipientMismatchError)")
    # 2 — overcharge above the quoted premium
    try:
        signer.sign_payment(domain=domain(), types=TRANSFER_TYPES,
                            message=message(me, writer, prem * 5), expected_to=writer)
        print(f"  {C_R}✗ overcharge was NOT refused (bug){C_0}")
    except X402AmountExceededError:
        print(f"  {C_G}✓{C_0} OVERCHARGE  value {prem*5} > cap {prem} → {C_B}refused{C_0} (X402AmountExceededError)")
    # 3 — drainer: payment against a non-U-token contract (the unbounded-allowance rug vector)
    try:
        signer.sign_payment(domain=domain(verifying="0xdeaddeaddeaddeaddeaddeaddeaddeaddeaddead"),
                            types=TRANSFER_TYPES, message=message(me, writer, prem), expected_to=writer)
        print(f"  {C_R}✗ drainer was NOT refused (bug){C_0}")
    except (X402PolicyError, X402BudgetExhaustedError):
        print(f"  {C_G}✓{C_0} DRAINER   non-U-token / unbounded domain → {C_B}refused{C_0} (X402PolicyError)")

    print(f"\n{C_D}  reputation prices it, the payee is pinned, the budget is metered, and the wallet")
    print(f"  refuses the rug — all from one self-custody signature.{C_0}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
