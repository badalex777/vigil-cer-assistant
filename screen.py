"""Vigil - Stage: abstract relevance screening."""
from __future__ import annotations

import config
import db
from llm import load_prompt, call_json

_SYSTEM = "You output only valid JSON. No markdown, no preamble."


def _fmt(profile, rec) -> str:
    tmpl = load_prompt(config.PROMPT_SCREEN)
    inclusion, exclusion = profile.criteria_for_track(rec["track"])
    # PubMed records key on pmid; ClinicalTrials.gov registrations have no pmid,
    # so fall back to their registry_id (NCT). The screener treats either as the ID.
    record_id = rec.get("pmid") or rec.get("registry_id") or ""
    return tmpl.format(
        device_name=profile.device_name,
        intended_purpose=profile.intended_purpose,
        track=rec["track"],
        inclusion_criteria="\n".join(f"- {c}" for c in inclusion),
        exclusion_criteria="\n".join(f"- {c}" for c in exclusion),
        pmid=record_id,
        title=rec.get("title", ""),
        abstract=rec.get("abstract", "") or "[no abstract available]",
    )


def screen_record(profile, rec, call=None) -> dict:
    call = call or call_json
    user = _fmt(profile, rec)
    result = call(config.MODEL_SCREEN, _SYSTEM, user, config.MAX_TOKENS_SCREEN)
    if result.get("_parse_error"):
        # Under-claim: unparsable -> uncertain, route to human.
        return {"verdict": "uncertain",
                "rationale": "Automated screen could not be parsed; flagged for human review."}
    verdict = result.get("verdict", "uncertain")
    if verdict not in ("include", "exclude", "uncertain"):
        verdict = "uncertain"
    return {"verdict": verdict, "rationale": result.get("rationale", "")}


def run(db_path, run_id, profile, records, call=None, progress=None):
    call = call or call_json
    progress = progress or (lambda s: None)
    counts = {"include": 0, "exclude": 0, "uncertain": 0}
    total = len(records)
    for i, rec in enumerate(records, 1):
        out = screen_record(profile, rec, call=call)
        # PubMed records key on pmid; ClinicalTrials.gov on registry_id.
        record_id = rec.get("pmid") or rec.get("registry_id", "")
        db.set_screen(db_path, run_id, record_id, out["verdict"],
                      out["rationale"], config.MODEL_SCREEN)
        counts[out["verdict"]] += 1
        # Report every 5 papers so the fragment can show a real progress bar.
        if i % 5 == 0 or i == total:
            progress(f"Screened {i}/{total} records")
    db.log(db_path, run_id, "screen",
           f"screened {len(records)}: {counts}")
    return counts
