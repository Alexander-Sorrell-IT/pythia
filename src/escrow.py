"""Forward-settlement ACT — wrap ERC-8183 escrow around a NarrativePit forward.

This is the on-chain lifecycle leg of NarrativePit. A written forward (proofs/pit/<id>.json)
becomes an ERC-8183 job whose budget is *capped by the writer's own reputation*
(credit_line = base * hit_rate, from credit.py — better record, bigger escrow it can command).

The job is driven through the kernel's real state machine:

  create_job -> register_job(policy) -> set_budget -> fund -> submit
                                                                |
  REALIZED (approve): let the dispute window elapse, then settle() pulls the
                      OptimisticPolicy's silence-approve verdict on-chain.
  MISSED   (reject):  dispute() (client-only), then vote_reject() — but ONLY if
                      this wallet is a whitelisted OptimisticPolicy voter; the
                      writer usually is NOT, so we report that honestly instead
                      of pretending a unilateral reject landed.

HONEST FRAMING — read this before quoting the demo:
  * This is optimistic-dispute settlement, NOT a live oracle and NOT a populated
    market. In the demo we play both agents.
  * `settle()` auto-approves only AFTER `submittedAt + disputeWindow` has elapsed;
    calling it earlier reverts. We do not fake an instant settlement.
  * `vote_reject()` is voter-gated on-chain. The self-custody writer wallet is not
    a voter unless it has been whitelisted by the policy admin, so the MISSED path
    can require a separate voter agent. We surface that, we don't hide it.
  * The verdict relayed here is one a judge can re-derive from the anchored
    snapshots (see verify_pit.py), not autonomous on-chain truth.

Funding is best-effort: we try a real fund() against the kernel's payment token; if
that token is unavailable / unapproved / the writer is short, we fall back to
SELF-escrow (the writer is also the provider/funder) so the lifecycle still demos
on-chain. Every step is wrapped so a revert returns a clear status dict, never crashes.

  python -m src.escrow open    <forward_id> [budget_cap]
  python -m src.escrow settle  <job_id> <REALIZED|MISSED>
"""
from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

from bnbagent import ERC8183Client

from .nsr import PIT, AGENT_ID
from .credit import hit_rate_from_proofs, credit_line

# Fallback job-lifetime cushion (seconds). create_job pre-flights expired_at against the
# policy's on-chain dispute_window and rejects jobs whose submit deadline is already past
# (SubmissionTooLate). We read the real window when we can and add a buffer; this constant
# is only the fallback when the window can't be read. The forward's own horizon governs the
# bet — this only governs the *job* envelope.
JOB_EXPIRY_FALLBACK_S = 8 * 86400
JOB_EXPIRY_BUFFER_S = 86400  # added on top of the on-chain dispute_window


def _client(idn) -> ERC8183Client:
    """Build an ERC-8183 facade from the agent's existing wallet provider (self-custody)."""
    net = os.getenv("NETWORK", "bsc-testnet")
    # SDK signature: ERC8183Client(wallet_provider=None, network="bsc-testnet", *, debug=False)
    return ERC8183Client(wallet_provider=idn.wallet, network=net)


def _tx(res) -> str | None:
    """Pull a tx hash out of a write result dict.

    _send_tx returns {"transactionHash": <hex str>, "status", "receipt"}, so the top-level
    value is already a hex string. We still defensively handle a HexBytes / receipt fallback.
    """
    if not isinstance(res, dict):
        return None
    h = res.get("transactionHash")
    if h:
        return h.hex() if hasattr(h, "hex") else h
    rcpt = res.get("receipt")
    if isinstance(rcpt, dict):
        rh = rcpt.get("transactionHash")
        return rh.hex() if hasattr(rh, "hex") else rh
    return None


def _deliverable_bytes(rec: dict) -> bytes | None:
    """Derive the 32-byte submit() deliverable from the forward's write_commit.

    write_commit is a '0x'-prefixed keccak hex (proof.commit_hash) = exactly 32 bytes.
    Returns None if it's missing/malformed so the caller can skip submit cleanly.
    """
    wc = rec.get("write_commit")
    if not isinstance(wc, str):
        return None
    try:
        b = bytes.fromhex(wc[2:] if wc.startswith("0x") else wc)
    except ValueError:
        return None
    return b if len(b) == 32 else None


def _cap_budget(budget_cap: float | None) -> tuple[int, float, float]:
    """Cap the requested budget by the writer's reputation-derived credit_line.

    Returns (budget_units, credit_line_value, hit_rate). Budget is whole token units; the
    demo uses small integer budgets so it survives whatever the payment-token decimals are.
    A 0-record rookie gets line==0 -> budget 0 (it cannot command escrow yet): the intended
    reputation gate, not a bug.
    """
    hr, _, _ = hit_rate_from_proofs()
    line = credit_line(hr)                       # base * hit_rate
    requested = line if budget_cap is None else min(float(budget_cap), line)
    budget = max(0, int(requested))
    return budget, line, hr


def _expired_at(cl: ERC8183Client) -> int:
    """now + on-chain dispute_window + buffer, falling back to a fixed cushion.

    create_job's pre-flight rejects jobs whose submit deadline (expired_at - dispute_window)
    is already past. Reading the real window keeps us correct even if the policy reconfigures
    it; the fallback covers an RPC hiccup / read revert.
    """
    now = int(time.time())
    try:
        window = int(cl.policy.dispute_window())
        return now + window + JOB_EXPIRY_BUFFER_S
    except Exception:
        return now + JOB_EXPIRY_FALLBACK_S


def open_forward_job(idn, forward_id: str, budget_cap: float | None = None) -> dict:
    """Open an ERC-8183 job for a written forward and drive it to SUBMITTED.

    create_job -> register_job(policy) -> set_budget(capped by credit_line) -> fund -> submit.

    register_job binds the OptimisticPolicy to the job — the SDK documents this as REQUIRED
    after createJob and before fund; without it settle()/dispute() have no policy to consult.
    submit() (provider == self) moves the job into SUBMITTED so the dispute window starts and
    settle() can later auto-approve — a job that is merely funded but never submitted cannot
    be settled.

    Funding: real fund() first; on any failure (payment token absent, allowance/balance short,
    revert) fall back to SELF-escrow, then to unfunded-but-job-landed. Never raises — returns a
    status dict with the tx hashes that landed plus `escrow_mode` of "funded" | "self-escrow"
    | "unfunded", and `submitted` (bool).
    """
    out: dict = {"ok": False, "forward_id": forward_id, "job_id": None,
                 "escrow_mode": "unfunded", "submitted": False, "tx": {}, "errors": []}

    rec_path = PIT / f"{forward_id}.json"
    if not rec_path.exists():
        out["errors"].append(f"no proof for forward {forward_id} at {rec_path}")
        return out
    try:
        rec = json.loads(rec_path.read_text())
    except (OSError, json.JSONDecodeError) as e:
        out["errors"].append(f"could not read/parse proof {rec_path}: {e}")
        return out
    fwd = rec.get("forward", {})

    budget, line, hr = _cap_budget(budget_cap)
    out["hit_rate"] = hr
    out["credit_line"] = line
    out["budget"] = budget

    try:
        cl = _client(idn)
    except Exception as e:
        out["errors"].append(f"client init failed: {e}")
        return out

    try:
        self_addr = idn.wallet.address
    except Exception as e:
        out["errors"].append(f"could not read wallet address: {e}")
        return out

    expired_at = _expired_at(cl)
    desc = (f"NarrativePit forward {forward_id}: {fwd.get('sector','?')} "
            f"share +{fwd.get('threshold_pct','?')}% in {fwd.get('horizon_s','?')}s "
            f"(commit {rec.get('write_commit','?')})")

    # 1) create_job. Writer is the client; provider == self so this wallet can submit() and so
    #    an approved escrow settles back to self in the self-escrow demo.
    try:
        res = cl.create_job(provider=self_addr, expired_at=expired_at, description=desc)
        job_id = res.get("jobId")
        out["job_id"] = int(job_id) if job_id is not None else None
        out["tx"]["create_job"] = _tx(res)
    except Exception as e:
        out["errors"].append(f"create_job failed: {e}")
        return out

    if out["job_id"] is None:
        out["errors"].append("create_job returned no jobId (no JobCreated log in receipt)")
        return out
    jid = out["job_id"]

    # 2) register_job — bind the policy (REQUIRED before fund). Wrapped: if it reverts (e.g.
    #    already registered, or a custom deployment auto-binds) we record it and keep going,
    #    because the demo value is the on-chain trail, not a single mandatory tx.
    try:
        res = cl.register_job(jid)
        out["tx"]["register_job"] = _tx(res)
    except Exception as e:
        out["errors"].append(f"register_job failed (settle may revert without a bound policy): {e}")

    # 3) set_budget (capped by reputation). A 0 budget still demos the create/register arc.
    try:
        res = cl.set_budget(jid, budget)
        out["tx"]["set_budget"] = _tx(res)
    except Exception as e:
        out["errors"].append(f"set_budget failed: {e}")
        return out

    # 4) fund — real first, self-escrow fallback. A 0 budget needs no fund tx and cannot submit
    #    (the kernel requires a funded job to submit), so we stop at the reputation gate.
    if budget <= 0:
        out["escrow_mode"] = "self-escrow"
        out["ok"] = True
        out["note"] = ("credit_line is 0 (no settled wins yet) — job opened with 0 budget; "
                       "not submitted (kernel requires a funded job to submit)")
        return out

    funded = False
    try:
        res = cl.fund(jid, budget)
        out["tx"]["fund"] = _tx(res)
        out["escrow_mode"] = "funded"
        funded = True
    except Exception as e:
        out["errors"].append(f"real fund failed, falling back to self-escrow: {e}")
        # self-escrow fallback: writer funds its own job (provider == self) so the lifecycle
        # still lands on-chain. approve_floor=0 forces an exact approve (no 100-token
        # stablecoin floor) for whatever the payment token is.
        try:
            res = cl.fund(jid, budget, approve_floor=0)
            out["tx"]["fund"] = _tx(res)
            out["escrow_mode"] = "self-escrow"
            funded = True
        except Exception as e2:
            out["errors"].append(f"self-escrow fund failed: {e2}")
            out["escrow_mode"] = "unfunded"
            out["ok"] = bool(out["tx"].get("create_job"))
            return out

    # 5) submit — provider (== self) submits the forward's write_commit as the 32-byte
    #    deliverable, moving the job to SUBMITTED so the dispute window opens. Without this,
    #    settle() reverts (nothing to approve). Wrapped: a submit revert still leaves a funded
    #    job on-chain, so we report submitted=False rather than crash.
    if funded:
        deliv = _deliverable_bytes(rec)
        if deliv is None:
            out["errors"].append("write_commit is not a 32-byte hash; skipped submit")
        else:
            try:
                res = cl.submit(jid, deliv, {"deliverable_url": f"narrativepit://forward/{forward_id}"})
                out["tx"]["submit"] = _tx(res)
                out["submitted"] = True
            except Exception as e:
                out["errors"].append(f"submit failed (job funded but not submitted): {e}")

    out["ok"] = bool(out["tx"].get("fund"))
    return out


def settle_forward(idn, job_id: int, verdict: str) -> dict:
    """Settlement relay for an opened+submitted forward job.

    REALIZED -> settle()                    (silence-approve once the dispute window elapses)
    MISSED   -> dispute(), then vote_reject() IFF this wallet is a whitelisted voter, then settle()

    DISPUTE IS ONLY EVER CALLED IFF verdict == "MISSED". Any other verdict takes the approve
    path. Honest about on-chain limits: settle() reverts until submittedAt + disputeWindow has
    elapsed, and vote_reject() reverts for a non-voter — both are reported, not faked. Never
    raises; returns a status dict with tx hashes and the `action` taken.
    """
    out: dict = {"ok": False, "job_id": int(job_id), "verdict": verdict,
                 "action": None, "tx": {}, "errors": []}

    v = (verdict or "").strip().upper()
    if v not in ("REALIZED", "MISSED"):
        out["errors"].append(f"unknown verdict {verdict!r}; expected REALIZED or MISSED")
        return out

    try:
        cl = _client(idn)
    except Exception as e:
        out["errors"].append(f"client init failed: {e}")
        return out

    jid = int(job_id)

    if v == "REALIZED":
        # Silence-approve: relay the policy verdict on-chain. Reverts if the dispute window
        # has not yet elapsed — surfaced verbatim so the caller knows to wait, not retry blind.
        out["action"] = "approve"
        try:
            res = cl.settle(jid)
            out["tx"]["settle"] = _tx(res)
            out["ok"] = True
        except Exception as e:
            out["errors"].append(
                f"settle (approve) failed — likely the dispute window has not elapsed yet "
                f"(settle auto-approves only after submittedAt + disputeWindow): {e}"
            )
        return out

    # v == "MISSED" — the ONLY branch that ever disputes.
    out["action"] = "dispute"
    try:
        res = cl.dispute(jid)
        out["tx"]["dispute"] = _tx(res)
    except Exception as e:
        out["errors"].append(f"dispute failed (client-only, within window, job must be submitted): {e}")
        return out

    # vote_reject is voter-gated on-chain. Check first so we report honestly instead of firing
    # a tx that reverts NotVoter. The self-custody writer is usually NOT a whitelisted voter;
    # in that case the reject needs a separate voter agent (we play both in the demo).
    try:
        addr = idn.wallet.address
        is_voter = bool(cl.policy.is_voter(addr))
    except Exception as e:
        is_voter = False
        out["errors"].append(f"could not check voter status (assuming non-voter): {e}")

    if not is_voter:
        out["action"] = "dispute (reject needs a whitelisted voter)"
        out["note"] = ("disputed on-chain; this wallet is not an OptimisticPolicy voter, so "
                       "vote_reject would revert. A whitelisted voter agent must cast the reject "
                       "vote, then settle() applies it. Dispute is the part this wallet can land.")
        out["ok"] = bool(out["tx"].get("dispute"))
        return out

    out["action"] = "dispute+reject"
    try:
        res = cl.vote_reject(jid)
        out["tx"]["vote_reject"] = _tx(res)
    except Exception as e:
        out["errors"].append(f"vote_reject failed: {e}")
        out["ok"] = bool(out["tx"].get("dispute"))
        return out

    # Apply the now-rejected verdict on-chain (permissionless; safe to attempt).
    try:
        res = cl.settle(jid)
        out["tx"]["settle"] = _tx(res)
        out["ok"] = True
    except Exception as e:
        out["errors"].append(f"settle (apply reject) failed: {e}")
        out["ok"] = bool(out["tx"].get("vote_reject"))
    return out


def main(argv: list[str]) -> None:
    try:
        from dotenv import load_dotenv; load_dotenv()
    except Exception:
        pass

    if not argv or argv[0] not in ("open", "settle"):
        print("usage: python -m src.escrow open <forward_id> [budget_cap] "
              "| settle <job_id> <REALIZED|MISSED>")
        return

    from .identity import Identity
    idn = Identity(); idn.agent_id = AGENT_ID

    if argv[0] == "open":
        if len(argv) < 2:
            print("usage: python -m src.escrow open <forward_id> [budget_cap]")
            return
        cap = float(argv[2]) if len(argv) > 2 else None
        res = open_forward_job(idn, argv[1], cap)
    else:
        if len(argv) < 3:
            print("usage: python -m src.escrow settle <job_id> <REALIZED|MISSED>")
            return
        res = settle_forward(idn, int(argv[1]), argv[2])

    print(json.dumps(res, indent=1, default=str))


if __name__ == "__main__":
    main(sys.argv[1:])
