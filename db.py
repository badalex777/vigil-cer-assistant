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
    appraisal_status TEXT DEFAULT 'pending',         -- 'pending'|'complete'|'appraisal_incomplete'
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
"""


@contextmanager
def connect(db_path: str):
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db(db_path: str):
    with connect(db_path) as c:
        c.executescript(SCHEMA)


def log(db_path: str, run_id: str, stage: str, message: str):
    with connect(db_path) as c:
        c.execute("INSERT INTO run_log VALUES (?,?,?,?)",
                  (run_id, time.time(), stage, message))


def start_run(db_path: str, run_id: str, profile):
    with connect(db_path) as c:
        c.execute(
            "INSERT OR REPLACE INTO runs VALUES (?,?,?,?,?)",
            (run_id, profile.device_name, profile.run_scope_hash(),
             json.dumps(profile.to_dict()), time.time()),
        )


def upsert_record(db_path: str, run_id: str, rec: dict):
    cols = ["pmid", "track", "title", "abstract", "journal", "year", "doi"]
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
