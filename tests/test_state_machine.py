"""
Vigil - run state machine tests (Block 2).

No network, no API. Verifies:
  - the lifecycle advances draft -> strings_approved -> locked -> running ->
    phase_b -> complete,
  - illegal (skip/backward) transitions are refused,
  - editing scope AFTER lock is refused (require_editable raises),
  - approved search strings are frozen verbatim and retrievable.

Run: python tests/test_state_machine.py
"""
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import db


def main():
    tmp = tempfile.mkdtemp()
    db_path = os.path.join(tmp, "state_test.db")
    db.init_db(db_path)
    run_id = "run_test_001"

    # --- init -> draft ---
    db.init_run_state(db_path, run_id, actor="prrc@client")
    assert db.current_state(db_path, run_id) == "draft", "should start in draft"
    assert not db.is_locked(db_path, run_id), "draft is not locked"
    db.require_editable(db_path, run_id)  # must NOT raise in draft

    # init is idempotent (re-opening a draft doesn't reset it)
    db.init_run_state(db_path, run_id, actor="someone_else")
    assert db.current_state(db_path, run_id) == "draft"

    # --- illegal skip: draft -> locked directly must fail ---
    try:
        db.lock_run(db_path, run_id, "deadbeef1234", actor="prrc@client")
        raise AssertionError("draft -> locked skip should have been refused")
    except db.StateError:
        pass

    # --- approve strings (draft -> strings_approved), frozen verbatim ---
    queries = {
        "device_specific": '("NPWT"[tiab] OR "VacuHeal"[tiab]) AND (English[lang])',
        "state_of_art": '("chronic wound"[tiab]) AND (English[lang])',
    }
    db.approve_strings(db_path, run_id, queries, actor="prrc@client")
    assert db.current_state(db_path, run_id) == "strings_approved"
    frozen = db.approved_queries(db_path, run_id)
    assert frozen == queries, "approved strings must be stored verbatim"

    # --- lock (strings_approved -> locked) stamps scope_hash ---
    db.lock_run(db_path, run_id, "abc123scope", actor="prrc@client")
    assert db.current_state(db_path, run_id) == "locked"
    assert db.is_locked(db_path, run_id), "should be locked now"
    st = db.get_run_state(db_path, run_id)
    assert st["locked_scope_hash"] == "abc123scope"
    assert st["locked_at"] is not None, "lock timestamp must be stamped"
    assert st["approved_at"] is not None, "approval timestamp must be stamped"

    # --- post-lock edit must be refused ---
    try:
        db.require_editable(db_path, run_id)
        raise AssertionError("require_editable should raise after lock")
    except db.StateError:
        pass

    # approving strings again after lock must also be refused
    try:
        db.approve_strings(db_path, run_id, queries, actor="prrc@client")
        raise AssertionError("re-approving after lock should be refused")
    except db.StateError:
        pass

    # --- remaining forward transitions ---
    db.mark_running(db_path, run_id, actor="system")
    assert db.current_state(db_path, run_id) == "running"
    db.mark_phase_b(db_path, run_id, actor="system")
    assert db.current_state(db_path, run_id) == "phase_b"
    db.mark_complete(db_path, run_id, actor="system")
    assert db.current_state(db_path, run_id) == "complete"

    # --- all six timestamps present and ordered ---
    st = db.get_run_state(db_path, run_id)
    ts = [st["created_at"], st["approved_at"], st["locked_at"],
          st["running_at"], st["phase_b_at"], st["complete_at"]]
    assert all(t is not None for t in ts), "every transition must be timestamped"
    assert ts == sorted(ts), "timestamps must be non-decreasing in lifecycle order"

    print("All state-machine assertions passed.")
    print("  draft -> strings_approved -> locked -> running -> phase_b -> complete OK")
    print("  illegal skip refused OK")
    print("  post-lock edit refused OK")
    print("  approved strings frozen verbatim OK")
    print("  all six transition timestamps stamped and ordered OK")


if __name__ == "__main__":
    main()
