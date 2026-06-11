"""Vigil - Stage: abstract relevance screening."""
from __future__ import annotations

import config
import db
from llm import load_prompt, call_json

_SYSTEM = "You output only valid JSON. No markdown, no preamble."


def _fmt(profile, rec) -> str:
    tmpl = load_prompt(config.PROMPT_SCREEN)
    inclusion, exclusion = profile.criteria_for_track(rec["track"])
    return tmpl.format(
        device_name=profile.device_name,
        intended_purpose=profile.intended_purpose,
        track=rec["track"],
        inclusion_criteria="\n".join(f"- {c}" for c in inclusion),
        exclusion_criteria="\n".join(f"- {c}" for c in exclusion),
        pmid=rec["pmid"],
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


def run(db_path, run_id, profile, records, call=None):
    call = call or call_json
    counts = {"include": 0, "exclude": 0, "uncertain": 0}
    for rec in records:
        out = screen_record(profile, rec, call=call)
        db.set_screen(db_path, run_id, rec["pmid"], out["verdict"],
                      out["rationale"], config.MODEL_SCREEN)
        counts[out["verdict"]] += 1
    db.log(db_path, run_id, "screen",
           f"screened {len(records)}: {counts}")
    return counts
