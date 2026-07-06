"""
Vigil - SQLite persistence (prototype).

Pipeline Spec ?15: SQLite is fine for the prototype (Postgres + pgvector later).
Tables mirror the spec's data model:
  - records        : every retrieved paper, per track, with screen + extraction state
  - outputs        : versioned generated documents (search report, CER draft, PRISMA)
  - signals        : SHARED PMS table; one-directional PMS -> CER handoff
  - run_log        : append-only audit log of pipeline events

Everything is keyed to a run_id + run_scope_hash so any output traces to a fixed scope.
"""
import sqlite3
import json
import time
from contextlib import contextmanager

SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (
    run_id          TEXT PRIMARY KEY,
    device_name     TEXT NOT NULL,
    scope_hash      TEXT NOT NULL,
    profile_json    TEXT NOT NULL,
    created_at      REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS records (
    run_id          TEXT NOT NULL,
    pmid            TEXT NOT NULL,
    track           TEXT NOT NULL,            -- 'device_specific' | 'state_of_art'
    title           TEXT,
    abstract        TEXT,
    journal         TEXT,
    year            TEXT,
    doi             TEXT,
    source          TEXT DEFAULT 'pubmed',    -- 'pubmed' | 'clinicaltrials_gov'
    entry_type      TEXT DEFAULT 'paper',     -- 'paper' | 'trial_registration'
    -- screening
    screen_verdict  TEXT,                     -- 'include' | 'exclude' | 'uncertain'
    screen_rationale TEXT,
    screen_model    TEXT,
    -- retrieval / appraisal (V1 abstracts-only; full-text path stubbed)
    retrieval_status TEXT DEFAULT 'abstract_only',  -- 'abstract_only'|'fulltext_retrieved'|'paywalled'|'not_retrieved'
    retrieval_source TEXT,                            -- 'pmc_xml'|'unpaywall_pdf'|'prrc_upload'|'paywalled_manual'|'auto_unverified'
    retrieval_url    TEXT,                            -- where the OA full text came from (audit)
    verification_result TEXT,                         -- 'verified_doi'|'verified_title'|'uncertain'|'mismatch'|'unverifiable'
    verification_score  REAL,
    verification_reason TEXT,
    appraisal_mode   TEXT DEFAULT 'abstract',        -- 'abstract' | 'fulltext'
    appraisal_status TEXT DEFAULT 'pending',         -- 'pending'|'complete'|'appraisal_incomplete'|'registry_evidence'
    fulltext_path    TEXT,                            -- path to PRRC-uploaded full-text PDF
    extraction_json  TEXT,
    PRIMARY KEY (run_id, pmid)
);

CREATE TABLE IF NOT EXISTS outputs (
    run_id      TEXT NOT NULL,
    kind        TEXT NOT NULL,                -- 'search_report' | 'cer_draft' | 'prisma_svg'
    version     INTEGER NOT NULL,
    content     TEXT NOT NULL,
    created_at  REAL NOT NULL,
    PRIMARY KEY (run_id, kind, version)
);

-- SHARED signals table: PMS Monitor writes here; CER runs READ it. One-directional.
CREATE TABLE IF NOT EXISTS signals (
    signal_id       TEXT PRIMARY KEY,
    source          TEXT,                     -- 'FDA_MAUDE' | 'MHRA' | ...
    source_ref      TEXT,                     -- FDA report number, etc. (traceability)
    udi_di          TEXT,                     -- model level, not unit level
    device_name     TEXT,
    summary         TEXT,
    severity        TEXT,                     -- 'low'|'medium'|'high'
    cer_relevance   TEXT,                     -- 'relevant'|'not_relevant'|'uncertain'
    triage_status   TEXT DEFAULT 'untriaged', -- human triage before action
    created_at      REAL
);

CREATE TABLE IF NOT EXISTS run_log (
    run_id   TEXT NOT NULL,
    ts       REAL NOT NULL,
    stage    TEXT NOT NULL,
    message  TEXT
);

-- Run lifecycle state machine (Block 2). One row per run.
-- States: draft -> strings_approved -> locked -> running -> phase_b -> complete
-- Each transition stamps its own UTC timestamp column for the audit trail.
-- approved_queries_json holds the search strings VERBATIM as the PRRC approved
-- them (the Literature Search Protocol crystallizes from this). locked_scope_hash
-- + locked_at prove the scope was frozen before any comprehensive search ran.
CREATE TABLE IF NOT EXISTS run_state (
    run_id                TEXT PRIMARY KEY,
    state                 TEXT NOT NULL,        -- current lifecycle state
    approved_queries_json TEXT,                 -- frozen search strings (verbatim)
    locked_scope_hash     TEXT,                 -- scope_hash stamped at lock
    actor                 TEXT,                 -- who performed the last transition
    created_at            REAL,
    approved_at           REAL,
    locked_at             REAL,
    running_at            REAL,
    phase_b_at            REAL,
    complete_at           REAL
);
"""

# Allowed forward transitions of the run state machine. Any other transition is
# refused (protects audit integrity: you cannot edit scope after lock, and you
# cannot skip the approval gate).
_STATE_ORDER = ["draft", "strings_approved", "locked", "running",
                "phase_b", "complete"]
_TS_COLUMN = {
    "draft": "created_at", "strings_approved": "approved_at",
    "locked": "locked_at", "running": "running_at",
    "phase_b": "phase_b_at", "complete": "complete_at",
}


class StateError(Exception):
    """Raised when a state transition or a post-lock edit is not permitted."""


@contextmanager
def connect(db_path: str):
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    # WAL mode: readers never block writers and writers never block readers.
    # Idempotent: already-WAL databases return "wal" with no state change.
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")   # safe with WAL; reduces fsync overhead
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db(db_path: str):
    with connect(db_path) as c:
        c.executescript(SCHEMA)
    _migrate_schema(db_path)


# Columns the code expects on `records`, with their SQL definitions. If an older
# database is missing any (created before these were added), add them in place so
# the app does not fail on "no such column". Safe to run on every init.
_RECORDS_EXPECTED_COLUMNS = {
    "track": "TEXT",
    "title": "TEXT",
    "abstract": "TEXT",
    "journal": "TEXT",
    "year": "TEXT",
    "doi": "TEXT",
    "source": "TEXT DEFAULT 'pubmed'",
    "entry_type": "TEXT DEFAULT 'paper'",
    "screen_verdict": "TEXT",
    "screen_rationale": "TEXT",
    "screen_model": "TEXT",
    "retrieval_status": "TEXT DEFAULT 'abstract_only'",
    "retrieval_source": "TEXT",
    "retrieval_url": "TEXT",
    "verification_result": "TEXT",
    "verification_score": "REAL",
    "verification_reason": "TEXT",
    "appraisal_mode": "TEXT DEFAULT 'abstract'",
    "appraisal_status": "TEXT DEFAULT 'pending'",
    "fulltext_path": "TEXT",
    "extraction_json": "TEXT",
}


def _migrate_schema(db_path: str):
    """Add any missing expected columns to existing tables (idempotent)."""
    with connect(db_path) as c:
        existing = {row["name"] for row in
                    c.execute("PRAGMA table_info(records)").fetchall()}
        if not existing:
            return  # table will have been created fresh with the full schema
        for col, ddl in _RECORDS_EXPECTED_COLUMNS.items():
            if col not in existing:
                try:
                    c.execute(f"ALTER TABLE records ADD COLUMN {col} {ddl}")
                except Exception:
                    pass  # column added concurrently or not critical


def log(db_path: str, run_id: str, stage: str, message: str):
    with connect(db_path) as c:
        c.execute("INSERT INTO run_log VALUES (?,?,?,?)",
                  (run_id, time.time(), stage, message))


def get_run_log(db_path: str, run_id: str) -> list:
    """Return the append-only event log for a run, oldest first, as dicts
    {ts, stage, message}. Feeds the Audit Trail export."""
    with connect(db_path) as c:
        rows = c.execute(
            "SELECT ts, stage, message FROM run_log WHERE run_id=? ORDER BY ts ASC",
            (run_id,)).fetchall()
        return [{"ts": r["ts"], "stage": r["stage"], "message": r["message"]}
                for r in rows]


def start_run(db_path: str, run_id: str, profile):
    with connect(db_path) as c:
        c.execute(
            "INSERT OR REPLACE INTO runs VALUES (?,?,?,?,?)",
            (run_id, profile.device_name, profile.run_scope_hash(),
             json.dumps(profile.to_dict()), time.time()),
        )


def upsert_record(db_path: str, run_id: str, rec: dict):
    # Unified record id: PubMed records use pmid; ClinicalTrials.gov registrations
    # have no pmid, so their NCT registry_id serves as the id (equally unique and
    # traceable). source/entry_type let downstream steps tell papers from trials.
    rec = dict(rec)
    if not rec.get("pmid"):
        rec["pmid"] = (rec.get("registry_id") or rec.get("external_id") or "")
    rec.setdefault("source", "pubmed")
    rec.setdefault("entry_type", "paper")
    cols = ["pmid", "track", "title", "abstract", "journal", "year", "doi",
            "source", "entry_type"]
    with connect(db_path) as c:
        c.execute(
            f"INSERT OR IGNORE INTO records (run_id,{','.join(cols)}) "
            f"VALUES (?,{','.join('?' for _ in cols)})",
            (run_id, *[rec.get(k) for k in cols]),
        )


def set_screen(db_path, run_id, pmid, verdict, rationale, model):
    with connect(db_path) as c:
        c.execute(
            "UPDATE records SET screen_verdict=?, screen_rationale=?, screen_model=? "
            "WHERE run_id=? AND pmid=?",
            (verdict, rationale, model, run_id, pmid),
        )


def set_extraction(db_path, run_id, pmid, extraction: dict, status="complete",
                   mode="abstract"):
    with connect(db_path) as c:
        c.execute(
            "UPDATE records SET extraction_json=?, appraisal_status=?, appraisal_mode=? "
            "WHERE run_id=? AND pmid=?",
            (json.dumps(extraction), status, mode, run_id, pmid),
        )


def attach_fulltext(db_path, run_id, pmid, path):
    """Record that the PRRC uploaded a full-text PDF for this paper."""
    with connect(db_path) as c:
        c.execute(
            "UPDATE records SET fulltext_path=?, retrieval_status='fulltext_retrieved' "
            "WHERE run_id=? AND pmid=?",
            (path, run_id, pmid),
        )


def set_retrieval_source(db_path, run_id, pmid, source, url):
    """Record HOW the full text was obtained (audit trail): pmc_xml / unpaywall_pdf
    / prrc_upload / paywalled_manual."""
    status = "fulltext_retrieved" if source in (
        "pmc_xml", "unpaywall_pdf", "prrc_upload") else "paywalled"
    with connect(db_path) as c:
        c.execute(
            "UPDATE records SET retrieval_source=?, retrieval_url=?, retrieval_status=? "
            "WHERE run_id=? AND pmid=?",
            (source, url, status, run_id, pmid),
        )


def set_verification(db_path, run_id, pmid, verdict: dict):
    """Record the identity-verification verdict for a retrieved full text (audit)."""
    with connect(db_path) as c:
        c.execute(
            "UPDATE records SET verification_result=?, verification_score=?, "
            "verification_reason=? WHERE run_id=? AND pmid=?",
            (verdict.get("result"), verdict.get("score"), verdict.get("reason"),
             run_id, pmid),
        )


def set_registry_evidence(db_path, run_id, pmid):
    """Flag a trial registration as counted registry evidence: included evidence
    that never enters the paper appraisal state machine (no PDF upload, no Opus
    appraisal)."""
    with connect(db_path) as c:
        c.execute(
            "UPDATE records SET appraisal_status='registry_evidence' "
            "WHERE run_id=? AND pmid=?",
            (run_id, pmid),
        )


def set_fulltext_appraisal(db_path, run_id, pmid, appraisal: dict, status="complete"):
    """Persist the full-text appraisal result (upgrades the paper from abstract-only)."""
    with connect(db_path) as c:
        c.execute(
            "UPDATE records SET extraction_json=?, appraisal_status=?, "
            "appraisal_mode='fulltext' WHERE run_id=? AND pmid=?",
            (json.dumps(appraisal), status, run_id, pmid),
        )


def retrieval_list(db_path, run_id):
    """Included papers and their current retrieval/appraisal state - the list the
    PRRC works through, uploading full text for each."""
    return get_records(db_path, run_id, "screen_verdict='include'")


def manual_upload_list(db_path, run_id):
    """Included papers that STILL need a PRRC upload: either no open-access copy was
    found, or an OA copy was found but FAILED identity verification (so we won't
    appraise it automatically). Kept as small as possible by auto-retrieval."""
    return get_records(
        db_path, run_id,
        "screen_verdict='include' AND appraisal_status='appraisal_incomplete' "
        "AND entry_type != 'trial_registration' "
        "AND (retrieval_source IN ('paywalled_manual','auto_unverified') "
        "     OR retrieval_source IS NULL)")


def get_records(db_path, run_id, where=""):
    with connect(db_path) as c:
        q = "SELECT * FROM records WHERE run_id=?"
        if where:
            q += f" AND {where}"
        return [dict(r) for r in c.execute(q, (run_id,)).fetchall()]


def save_output(db_path, run_id, kind, content):
    with connect(db_path) as c:
        row = c.execute(
            "SELECT COALESCE(MAX(version),0)+1 v FROM outputs WHERE run_id=? AND kind=?",
            (run_id, kind),
        ).fetchone()
        version = row["v"]
        c.execute("INSERT INTO outputs VALUES (?,?,?,?,?)",
                  (run_id, kind, version, content, time.time()))
        return version


def get_cer_relevant_signals(db_path, device_name):
    """A CER run reads CER-relevant, human-triaged PMS signals (one-directional)."""
    with connect(db_path) as c:
        return [dict(r) for r in c.execute(
            "SELECT * FROM signals WHERE device_name=? AND cer_relevance='relevant'",
            (device_name,)).fetchall()]


# --- Run state machine (Block 2) ---------------------------------------------

def init_run_state(db_path, run_id, actor=""):
    """Create the state row for a run in 'draft'. Idempotent: if it already
    exists, leaves it untouched (so re-opening a draft doesn't reset it)."""
    with connect(db_path) as c:
        exists = c.execute("SELECT 1 FROM run_state WHERE run_id=?",
                            (run_id,)).fetchone()
        if not exists:
            c.execute(
                "INSERT INTO run_state (run_id, state, actor, created_at) "
                "VALUES (?,?,?,?)", (run_id, "draft", actor, time.time()))


def get_run_state(db_path, run_id):
    """Return the state row as a dict, or None if not initialized."""
    with connect(db_path) as c:
        row = c.execute("SELECT * FROM run_state WHERE run_id=?",
                        (run_id,)).fetchone()
        return dict(row) if row else None


def current_state(db_path, run_id):
    """Convenience: just the state string (or None)."""
    st = get_run_state(db_path, run_id)
    return st["state"] if st else None


def is_locked(db_path, run_id):
    """True once the run has reached 'locked' or beyond - scope is immutable."""
    st = current_state(db_path, run_id)
    if st is None:
        return False
    return _STATE_ORDER.index(st) >= _STATE_ORDER.index("locked")


def require_editable(db_path, run_id):
    """Guard for any operation that would change scope. Refuses (raises
    StateError) once the run is locked. Call this before mutating the profile
    or search strings for a run."""
    if is_locked(db_path, run_id):
        raise StateError(
            f"Run {run_id} is locked; scope is immutable. "
            "Start a new run to change scope (auditability requirement).")


def _advance(db_path, run_id, target, actor=""):
    """Move the run to `target`, allowing only the next forward state.
    Stamps the target's timestamp column. Raises StateError on illegal moves."""
    if target not in _STATE_ORDER:
        raise StateError(f"Unknown state: {target}")
    st = current_state(db_path, run_id)
    if st is None:
        raise StateError(f"Run {run_id} has no state row; call init_run_state first.")
    cur_i, tgt_i = _STATE_ORDER.index(st), _STATE_ORDER.index(target)
    if tgt_i != cur_i + 1:
        raise StateError(
            f"Illegal transition {st} -> {target}. "
            f"Only forward-by-one transitions are allowed.")
    ts_col = _TS_COLUMN[target]
    with connect(db_path) as c:
        c.execute(
            f"UPDATE run_state SET state=?, actor=?, {ts_col}=? WHERE run_id=?",
            (target, actor, time.time(), run_id))
    log(db_path, run_id, "state", f"{st} -> {target}"
        + (f" by {actor}" if actor else ""))


def approve_strings(db_path, run_id, queries: dict, actor=""):
    """PRRC approves the (possibly edited) search strings. Freezes them verbatim
    and advances draft -> strings_approved. This is the search-strategy gate."""
    require_editable(db_path, run_id)  # can only approve from an editable state
    with connect(db_path) as c:
        c.execute("UPDATE run_state SET approved_queries_json=? WHERE run_id=?",
                  (json.dumps(queries), run_id))
    _advance(db_path, run_id, "strings_approved", actor)


def lock_run(db_path, run_id, scope_hash, actor=""):
    """Start Research: stamp the scope_hash + lock timestamp and advance
    strings_approved -> locked. After this, require_editable() refuses edits."""
    with connect(db_path) as c:
        c.execute("UPDATE run_state SET locked_scope_hash=? WHERE run_id=?",
                  (scope_hash, run_id))
    _advance(db_path, run_id, "locked", actor)


def mark_running(db_path, run_id, actor=""):
    _advance(db_path, run_id, "running", actor)


def mark_phase_b(db_path, run_id, actor=""):
    _advance(db_path, run_id, "phase_b", actor)


def mark_complete(db_path, run_id, actor=""):
    _advance(db_path, run_id, "complete", actor)


def approved_queries(db_path, run_id):
    """The frozen, PRRC-approved search strings (or None if not yet approved).
    The Literature Search Protocol renders from these."""
    st = get_run_state(db_path, run_id)
    if st and st.get("approved_queries_json"):
        return json.loads(st["approved_queries_json"])
    return None
