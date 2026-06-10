"""Vigil — Stage: adverse-event / performance extraction (abstract-level, V1)."""
from __future__ import annotations
import json

import config
import db
from llm import load_prompt, call_json

_SYSTEM = "You output only valid JSON. No markdown, no preamble. Unknown stays unknown."


def _fmt(profile, rec) -> str:
    tmpl = load_prompt(config.PROMPT_EXTRACT)
    return tmpl.format(
        pmid=rec["pmid"],
        title=rec.get("title", ""),
        abstract=rec.get("abstract", "") or "[no abstract available]",
    )


def extract_record(profile, rec, call=None) -> tuple[dict, str]:
    call = call or call_json
    user = _fmt(profile, rec)
    result = call(config.MODEL_EXTRACT, _SYSTEM, user, config.MAX_TOKENS_EXTRACT)
    if result.get("_parse_error"):
        return ({"pmid": rec["pmid"], "error": "extraction_parse_failed"},
                "appraisal_incomplete")
    result.setdefault("pmid", rec["pmid"])
    result["track"] = rec["track"]
    # Abstract-level extraction is, by MEDDEV §9.3 definition, an INCOMPLETE
    # appraisal — the full text has not been reviewed. It stays flagged until a
    # full-text PDF is uploaded and appraised (Phase B). This is intentional.
    return result, "appraisal_incomplete"


def run(db_path, run_id, profile, included_records, call=None):
    call = call or call_json
    n = 0
    for rec in included_records:
        extraction, status = extract_record(profile, rec, call=call)
        db.set_extraction(db_path, run_id, rec["pmid"], extraction, status,
                          mode="abstract")
        n += 1
    db.log(db_path, run_id, "extract",
           f"abstract-extracted {n} included records (flagged appraisal_incomplete)")
    return n
