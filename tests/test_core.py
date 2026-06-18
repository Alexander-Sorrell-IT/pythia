"""Offline unit tests for the NarrativePit core — no chain, no network.

Run from anywhere (a sys.path bootstrap below finds the project root so the suite
works whether invoked from the repo root or from tests/):

    python -m pytest tests/ -q

Covers the four pure pieces the on-chain demo stands on:
  (a) narrative.settle / parse_mcap  — REALIZED vs MISSED vs void, on hand-built cap-share snaps
  (b) proof.commit_hash              — deterministic across dict reordering, changes on any edit
  (c) credit math                    — premium / credit_line / hit_rate_from_proofs (tmp proof dir)
  (d) verify_pit.verify              — offline (idn=None): HASH+REPLAY green on a hand-built rec,
                                       every tamper goes red. ANCHOR-* are None (skipped) offline.

Honest scope: these assert the OFFLINE half of the proof (HASH + REPLAY) — the deterministic,
re-derivable core. They do NOT and cannot assert the on-chain half (ANCHOR-EXISTS / ANCHOR-ORDER):
those require BNB Chain and are exercised by `python -m src.verify_pit <id>` against real blocks.
The settlement is optimistic-dispute, not an oracle; REPLAY is what a disputer re-runs.

The hand-built `rec` dicts mirror the on-chain proof JSON shape (see src/nsr.py):
  {id, agent_id, forward{sector,threshold_pct,horizon_s,emitted_at},
   write_snapshot{caps,names,ts}, write_commit, write_block, expires_at,
   expiry_snapshot{caps,names,ts}, verdict, settle_detail, settle_commit, settle_block}
"""
from __future__ import annotations

import sys
from pathlib import Path

# --- path bootstrap: make `import src.*` work regardless of pytest's invocation cwd --------- #
# There is no conftest.py in this repo, so a bare `pytest tests/test_core.py` from inside
# tests/ would otherwise fail to import `src`. Insert the project root (parent of tests/) once.
_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import json

import pytest

from src.narrative import NarrativeForward, NarrativeSnapshot, settle, parse_mcap
from src.proof import commit_hash
from src.credit import premium, credit_line, hit_rate_from_proofs
from src.nsr import write_commit_for, settle_commit_for
from src.verify_pit import verify


# --------------------------------------------------------------------------- #
# Shared fixtures — two snapshots where the 'ai' sector's SHARE moves 50%->60%
# (cap 100->150 against a flat 'memes' 100). Used to build a REALIZED forward.
# --------------------------------------------------------------------------- #
def _write_snap() -> NarrativeSnapshot:
    return NarrativeSnapshot(
        caps={"ai": 100.0, "memes": 100.0},
        names={"ai": "AI", "memes": "Memes"},
        ts=1_000,
    )


def _expiry_snap() -> NarrativeSnapshot:
    return NarrativeSnapshot(
        caps={"ai": 150.0, "memes": 100.0},
        names={"ai": "AI", "memes": "Memes"},
        ts=2_000,
    )


# --------------------------------------------------------------------------- #
# (a) narrative.settle — cap-SHARE delta vs threshold
# --------------------------------------------------------------------------- #
def test_settle_realized():
    # share 0.50 -> 0.60  =>  +20% growth, threshold +5% -> REALIZED
    fwd = NarrativeForward(sector="ai", threshold_pct=5.0, horizon_s=600, emitted_at=1_000)
    realized, detail = settle(fwd, _write_snap(), _expiry_snap())
    assert realized is True
    assert "REALIZED" in detail


def test_settle_missed():
    # same +20% growth, but threshold +25% -> MISSED (identical snapshots, only the bar moves)
    fwd = NarrativeForward(sector="ai", threshold_pct=25.0, horizon_s=600, emitted_at=1_000)
    realized, detail = settle(fwd, _write_snap(), _expiry_snap())
    assert realized is False
    assert "MISSED" in detail


def test_settle_void_when_sector_absent_at_write():
    # sector with zero share at write -> void (returns False, never REALIZED)
    fwd = NarrativeForward(sector="ghost", threshold_pct=1.0, horizon_s=600, emitted_at=1_000)
    realized, detail = settle(fwd, _write_snap(), _expiry_snap())
    assert realized is False
    assert "void" in detail
    # a void forward must never be reported as REALIZED, whatever the bar
    assert "REALIZED" not in detail


def test_settle_boundary_is_strict_due_to_float():
    # Regression-pin, not aspiration. At the "natural" exact boundary the bar is +20.0% and the
    # realized growth is +20.0% — but settle() computes (0.6-0.5)/0.5*100 in IEEE-754, which is
    # 19.999999999999996, so `>= 20.0` is False and the verdict is MISSED. This is a real property
    # of the deployed settle(); pinning it means a future "tidy-up" that changes the comparison or
    # rounding will trip this test instead of silently shifting settlement semantics under live bets.
    fwd = NarrativeForward(sector="ai", threshold_pct=20.0, horizon_s=600, emitted_at=1_000)
    realized, detail = settle(fwd, _write_snap(), _expiry_snap())
    assert realized is False
    assert "MISSED" in detail


def test_settle_share_drop_is_missed():
    # share shrinks (other sector pumps) -> negative growth -> MISSED even at a 0% bar
    fwd = NarrativeForward(sector="ai", threshold_pct=0.0, horizon_s=600, emitted_at=1_000)
    drop = NarrativeSnapshot(caps={"ai": 100.0, "memes": 300.0}, ts=2_000)
    realized, detail = settle(fwd, _write_snap(), drop)
    assert realized is False
    assert "MISSED" in detail


def test_parse_mcap_units():
    assert parse_mcap("2.21 T") == pytest.approx(2.21e12)
    assert parse_mcap("48.3 B") == pytest.approx(48.3e9)
    assert parse_mcap("500 M") == pytest.approx(5.0e8)
    assert parse_mcap("1,000") == pytest.approx(1000.0)
    assert parse_mcap(None) == 0.0


def test_parse_mcap_numeric_passthrough():
    # the int/float branch (e.g. a raw marketCapUsd number) -> float, no unit parsing
    assert parse_mcap(1.5e9) == pytest.approx(1.5e9)
    assert parse_mcap(42) == pytest.approx(42.0)
    assert isinstance(parse_mcap(42), float)


# --------------------------------------------------------------------------- #
# (b) proof.commit_hash — deterministic serialization
# --------------------------------------------------------------------------- #
def test_commit_hash_is_0x_keccak():
    h = commit_hash({"a": 1})
    assert isinstance(h, str)
    assert h.startswith("0x")
    assert len(h) == 66  # 0x + 32 bytes hex
    assert all(c in "0123456789abcdef" for c in h[2:])  # lowercase hex, no 0X/uppercase drift


def test_commit_hash_stable_across_dict_reordering():
    # same content, different insertion order -> identical hash (sorted keys, canonical floats)
    a = {"sector": "ai", "threshold_pct": 5.0, "snap": {"ai": 100.0, "memes": 100.0}}
    b = {"snap": {"memes": 100.0, "ai": 100.0}, "threshold_pct": 5.0, "sector": "ai"}
    assert commit_hash(a) == commit_hash(b)


def test_commit_hash_changes_on_edit():
    base = {"sector": "ai", "threshold_pct": 5.0}
    edited = {"sector": "ai", "threshold_pct": 5.1}
    assert commit_hash(base) != commit_hash(edited)


def test_commit_hash_float_path_is_stable():
    # _canon formats floats to fixed precision (f"{v:.8f}"), so float noise below 1e-8 collapses:
    # 0.1+0.2 == 0.30000000000000004 -> "0.30000000" == the literal 0.30000000.
    # NOTE int and float do NOT canonicalize together (see next test) — only the float path is pinned.
    assert commit_hash({"x": 5.0}) == commit_hash({"x": 5.0})
    assert commit_hash({"x": 0.1 + 0.2}) == commit_hash({"x": 0.30000000})


def test_commit_hash_bool_and_int_do_not_collide():
    # _canon special-cases bool BEFORE int/float: True stays a JSON bool ("true"), 1 stays "1".
    # If that order ever regressed, True would canonicalize as a number and collide with 1 — which
    # would let a record flip a boolean flag without changing its commit. Guard against it.
    assert commit_hash({"x": True}) != commit_hash({"x": 1})
    assert commit_hash({"x": False}) != commit_hash({"x": 0})
    assert commit_hash({"x": True}) == commit_hash({"x": True})


# --------------------------------------------------------------------------- #
# (c) credit — premium / credit_line / hit_rate_from_proofs
# --------------------------------------------------------------------------- #
def test_premium_inverse_of_hit_rate():
    assert premium(1.0) == 0.0       # perfect record -> zero spread
    assert premium(0.0) == 100.0     # no record     -> max spread
    assert premium(0.2) == 80.0      # rookie #1446


def test_credit_line_scales_with_hit_rate():
    assert credit_line(1.0) == 1000.0  # veteran #1422
    assert credit_line(0.0) == 0.0
    assert credit_line(0.2) == 200.0   # rookie #1446


def test_hit_rate_from_proofs(tmp_path):
    verdicts = ["REALIZED", "REALIZED", "MISSED", "REALIZED", "MISSED"]
    for i, v in enumerate(verdicts):
        (tmp_path / f"{i:04d}.json").write_text(json.dumps({"id": f"{i:04d}", "verdict": v}))
    # an unsettled forward (no verdict yet) must be ignored, not counted as a miss
    (tmp_path / "9999.json").write_text(json.dumps({"id": "9999"}))

    hr, realized, total = hit_rate_from_proofs(tmp_path)
    assert (realized, total) == (3, 5)
    assert hr == pytest.approx(0.6)


def test_hit_rate_all_missed_is_zero_but_counted(tmp_path):
    # distinct from the empty-dir early return: settled>0, realized=0 -> hr 0.0 with total=2.
    # (A forecaster who settled and missed everything has hit_rate 0, not "no record".)
    for i in range(2):
        (tmp_path / f"{i:04d}.json").write_text(json.dumps({"id": f"{i:04d}", "verdict": "MISSED"}))
    hr, realized, total = hit_rate_from_proofs(tmp_path)
    assert (hr, realized, total) == (0.0, 0, 2)


def test_hit_rate_empty_dir_is_zero(tmp_path):
    hr, realized, total = hit_rate_from_proofs(tmp_path)
    assert (hr, realized, total) == (0.0, 0, 0)


# --------------------------------------------------------------------------- #
# (d) verify_pit.verify — offline (idn=None): HASH + REPLAY only
# --------------------------------------------------------------------------- #
def _good_rec() -> dict:
    """A hand-built proof JSON whose commits and verdict are internally consistent.

    Matches the on-chain proof shape; commits are derived with the same helpers nsr/do_settle
    use, so HASH is green and REPLAY recomputes the committed REALIZED verdict.
    """
    fid = "0001"
    forward = {"sector": "ai", "threshold_pct": 5.0, "horizon_s": 600, "emitted_at": 1_000}
    wsnap = {"caps": {"ai": 100.0, "memes": 100.0},
             "names": {"ai": "AI", "memes": "Memes"}, "ts": 1_000}
    esnap = {"caps": {"ai": 150.0, "memes": 100.0},
             "names": {"ai": "AI", "memes": "Memes"}, "ts": 2_000}
    verdict = "REALIZED"
    return {
        "id": fid,
        "agent_id": 1422,
        "forward": forward,
        "write_snapshot": wsnap,
        "write_commit": write_commit_for(forward, wsnap),
        "write_block": 100,
        "expires_at": 1_600,
        "expiry_snapshot": esnap,
        "verdict": verdict,
        "settle_detail": "hand-built",
        "settle_commit": settle_commit_for(fid, esnap, verdict),
        "settle_block": 200,
    }


def _checks_by_name(checks):
    """checks is a list of (name, passed_or_None, detail); index it by name."""
    return {name: (passed, detail) for name, passed, detail in checks}


def test_good_rec_is_internally_consistent_before_verify():
    # Guards the fixture itself: if write_commit_for / settle_commit_for signatures ever drift,
    # this fails loudly here rather than masquerading as a verify() bug downstream.
    rec = _good_rec()
    assert rec["write_commit"] == write_commit_for(rec["forward"], rec["write_snapshot"])
    assert rec["settle_commit"] == settle_commit_for(
        rec["id"], rec["expiry_snapshot"], rec["verdict"])


def test_verify_offline_four_green_minus_anchors():
    rec = _good_rec()
    ok, checks = verify(rec, idn=None)
    by = _checks_by_name(checks)

    # exactly the four named checks, no more no less
    assert set(by) == {"HASH", "REPLAY", "ANCHOR-EXISTS", "ANCHOR-ORDER"}
    assert by["HASH"][0] is True
    assert by["REPLAY"][0] is True
    assert by["ANCHOR-EXISTS"][0] is None   # skipped offline (None, NOT False)
    assert by["ANCHOR-ORDER"][0] is None    # skipped offline (None, NOT False)
    assert ok is True                        # None checks are excluded from the verdict aggregate


def test_verify_offline_tampered_write_commit_fails_hash():
    rec = _good_rec()
    rec["write_commit"] = "0x" + "de" * 32  # forged commit, snapshots untouched
    ok, checks = verify(rec, idn=None)
    by = _checks_by_name(checks)
    assert by["HASH"][0] is False
    assert ok is False


def test_verify_offline_tampered_settle_commit_fails_hash():
    rec = _good_rec()
    rec["settle_commit"] = "0x" + "ab" * 32  # forge only the settle-side commit
    ok, checks = verify(rec, idn=None)
    by = _checks_by_name(checks)
    assert by["HASH"][0] is False     # HASH ANDs write & settle commits — settle alone breaks it
    assert by["REPLAY"][0] is True    # snapshots/verdict still consistent, so REPLAY stays green
    assert ok is False


def test_verify_offline_tampered_verdict_fails_replay():
    rec = _good_rec()
    # flip the verdict but re-derive settle_commit so HASH still passes — only REPLAY can catch it
    rec["verdict"] = "MISSED"
    rec["settle_commit"] = settle_commit_for(rec["id"], rec["expiry_snapshot"], "MISSED")
    ok, checks = verify(rec, idn=None)
    by = _checks_by_name(checks)
    assert by["HASH"][0] is True        # the lie is self-consistently hashed...
    assert by["REPLAY"][0] is False     # ...but re-running settle() over the committed snaps catches it
    assert ok is False


def test_verify_offline_tampered_snapshot_fails():
    rec = _good_rec()
    # edit the committed expiry cap (the bet now actually MISSED) without touching commit/verdict
    rec["expiry_snapshot"]["caps"]["ai"] = 100.0  # share flat -> growth 0% < 5% -> should be MISSED
    ok, checks = verify(rec, idn=None)
    by = _checks_by_name(checks)
    # HASH breaks (commit no longer matches the edited snap) AND REPLAY breaks (recomputed MISSED)
    assert by["HASH"][0] is False
    assert by["REPLAY"][0] is False
    assert ok is False
