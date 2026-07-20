"""Vigil - Stage: adverse-event / performance extraction (abstract-level, V1)."""
from __future__ import annotations
import json

import config
import db
from llm import load_prompt, call_json, split_stable_variable

_SYSTEM = "You output only valid JSON. No markdown, no preamble. Unknown stays unknown."

# The opening intro + first HARD RULES bullet are the only genuinely
# record-independent part of this template - {pmid} is already embedded in
# the very next bullet ("traceable to this source (PMID {pmid})"), so the
# cacheable prefix has to end before that, not at the SOURCE header (Block 5X).
_STABLE_MARKER = "\n- Every extracted value must be traceable to this source"


def _fmt(profile, rec) -> tuple[str, str]:
    """Return (stable, variable). stable is the cacheable prefix (the
    record-independent opening lines - no per-item text). variable is
    everything from the first PMID-bearing rule onward, formatted with this
    record's pmid/title/abstract."""
    tmpl = load_prompt(config.PROMPT_EXTRACT)
    stable_tmpl, variable_tmpl = split_stable_variable(tmpl, _STABLE_MARKER)
    variable = variable_tmpl.format(
        pmid=rec["pmid"],
        title=rec.get("title", ""),
        abstract=rec.get("abstract", "") or "[no abstract available]",
    )
    return stable_tmpl, variable


def extract_record(profile, rec, call=None) -> tuple[dict, str]:
    call = call or call_json
    stable, variable = _fmt(profile, rec)
    result = call(config.MODEL_EXTRACT, _SYSTEM, stable, variable, config.MAX_TOKENS_EXTRACT)
    if result.get("_parse_error"):
        return ({"pmid": rec["pmid"], "error": "extraction_parse_failed"},
                "appraisal_incomplete")
    result.setdefault("pmid", rec["pmid"])
    result["track"] = rec["track"]
    # Abstract-level extraction is, by MEDDEV ?9.3 definition, an INCOMPLETE
    # appraisal - the full text has not been reviewed. It stays flagged until a
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
