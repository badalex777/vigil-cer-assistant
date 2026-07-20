"""
Vigil - Stage: full-text appraisal (Phase B).

Performs a MEDDEV 2.7/1 rev 4 Appendix A6 appraisal (methodological quality,
relevance, data contribution) plus full extraction on the COMPLETE paper, moving
it from `appraisal_incomplete` to fully appraised.

Full text arrives from ONE of three sources (see retrieve.py + manual upload):
  - PMC open access  -> plain text / XML  -> text appraisal
  - Unpaywall OA PDF -> pdf bytes         -> native-PDF appraisal
  - PRRC manual upload (residual paywalled) -> pdf bytes -> native-PDF appraisal

Auto-retrieval handles the bulk; the PRRC only uploads the residual. Vigil never
circumvents a paywall.

PDFs are sent NATIVELY to Claude (tables/figures survive). PMC text is embedded.
"""
from __future__ import annotations

import config
import db
from llm import load_prompt, call_json_pdf, call_json_fulltext_text, split_stable_variable

_SYSTEM = ("You output only valid JSON. No markdown, no preamble. "
           "Unknown stays unknown. You describe and appraise; you never conclude "
           "on safety, efficacy, equivalence, or compliance.")

# Stable prefix ends right before the first per-paper PMID citation embedded
# in the HARD RULES section ("traceable to this source (PMID {pmid})") -
# everything before that is identical across every appraisal call in a run
# (Block 5X). pmid/title/device_name/intended_purpose all appear later
# (SOURCE header, IDENTITY CHECK, JSON schema), so the variable half still
# needs all four formatted in.
_STABLE_MARKER = "\n- Every extracted value is traceable to this source"


def _fmt(profile, rec) -> tuple[str, str]:
    """Return (stable, variable). stable is the cacheable prefix (intro +
    WHAT MEDDEV A6 REQUIRES + the first HARD RULES bullet - no per-paper
    text). variable is everything from the PMID-citation rule onward,
    formatted with this paper's identifiers."""
    tmpl = load_prompt(config.PROMPT_APPRAISE)
    stable_tmpl, variable_tmpl = split_stable_variable(tmpl, _STABLE_MARKER)
    variable = variable_tmpl.format(
        pmid=rec["pmid"],
        title=rec.get("title", ""),
        device_name=profile.device_name,
        intended_purpose=profile.intended_purpose,
    )
    return stable_tmpl, variable


def appraise_pdf(profile, rec, pdf_bytes, call=None):
    call = call or call_json_pdf
    stable, variable = _fmt(profile, rec)
    result = call(config.MODEL_APPRAISE, _SYSTEM, stable, variable, pdf_bytes,
                  config.MAX_TOKENS_APPRAISE)
    return _finish(rec, result)


def appraise_text(profile, rec, fulltext, call=None):
    call = call or call_json_fulltext_text
    stable, variable = _fmt(profile, rec)
    result = call(config.MODEL_APPRAISE, _SYSTEM, stable, variable, fulltext,
                  config.MAX_TOKENS_APPRAISE)
    return _finish(rec, result)


def _safe_appraise(db_path, run_id, rec, fn):
    """Run one paper's appraisal call, never letting a hang or error on this
    paper take down the whole loop. On timeout/exception: log pmid + title
    and fail safe to appraisal_incomplete so the paper is honestly flagged,
    not silently dropped, and the loop moves on to the next paper."""
    try:
        return fn()
    except Exception as e:
        pmid = rec["pmid"]
        db.log(db_path, run_id, "appraise_error",
               f"PMID {pmid} ({rec.get('title', '')[:200]}): "
               f"{type(e).__name__}: {e}")
        return ({"pmid": pmid, "error": "appraisal_exception",
                 "exception": type(e).__name__}, "appraisal_incomplete")


def _finish(rec, result):
    if result.get("_parse_error"):
        # Under-claim: failed appraisal leaves the paper flagged, not promoted.
        return ({"pmid": rec["pmid"], "error": "appraisal_parse_failed"},
                "appraisal_incomplete")
    if result.get("identity_mismatch"):
        # LLM self-check (defense in depth) caught a wrong document. Do not promote.
        return ({"pmid": rec["pmid"], "error": "identity_mismatch",
                 "reason": result.get("reason", "")}, "appraisal_incomplete")
    result.setdefault("pmid", rec["pmid"])
    result["track"] = rec["track"]
    result["appraisal_mode"] = "fulltext"
    return result, "complete"


def run_from_retrieval(db_path, run_id, profile, retrieval: dict,
                       pdf_call=None, text_call=None, progress=lambda s: None):
    """Appraise everything auto-retrieved (PMC text or Unpaywall PDF).

    retrieval: {pmid: {status, kind, text, pdf_bytes, source_url}}  (from retrieve.py)
    Papers with kind None (paywalled_manual) are skipped here - they go to the
    manual-upload list and are handled by run_from_uploads().
    """
    results = {}
    for pmid, res in retrieval.items():
        if res["kind"] is None:
            continue  # residual paywalled -> manual upload path
        rows = db.get_records(db_path, run_id, f"pmid='{pmid}'")
        if not rows:
            continue
        rec = rows[0]
        db.set_retrieval_source(db_path, run_id, pmid, res["status"], res["source_url"])
        if res["kind"] == "pdf":
            appraisal, status = _safe_appraise(
                db_path, run_id, rec,
                lambda: appraise_pdf(profile, rec, res["pdf_bytes"], call=pdf_call))
        else:  # 'xml_text'
            appraisal, status = _safe_appraise(
                db_path, run_id, rec,
                lambda: appraise_text(profile, rec, res["text"], call=text_call))
        db.set_fulltext_appraisal(db_path, run_id, pmid, appraisal, status)
        results[pmid] = status
        progress(f"  appraised PMID {pmid} ({res['status']}): {status}")
    db.log(db_path, run_id, "appraise_auto",
           f"auto-appraised {len(results)}: {results}")
    return results


def run_from_uploads(db_path, run_id, profile, uploads: dict, pdf_call=None,
                     progress=lambda s: None):
    """Appraise PRRC-uploaded PDFs (the residual papers).
    uploads: {pmid: pdf_bytes}.

    Identity is verified as a SOFT check here (the PRRC deliberately chose the
    file): the verdict is recorded for the audit trail and a mismatch is surfaced,
    but the upload is still appraised since a human made the association.
    """
    import verify
    results = {}
    for pmid, pdf_bytes in uploads.items():
        rows = db.get_records(db_path, run_id, f"pmid='{pmid}'")
        if not rows:
            continue
        rec = rows[0]
        verdict = verify.verify(rec, verify.extract_pdf_identifiers(pdf_bytes))
        db.set_verification(db_path, run_id, pmid, verdict)
        if verdict["result"] not in verify.VERIFIED:
            progress(f"  ? PMID {pmid}: uploaded file did not verify "
                     f"({verdict['result']}, score {verdict['score']}) - "
                     f"appraising as PRRC chose it; flagged in audit trail.")
        db.attach_fulltext(db_path, run_id, pmid,
                           f"{config.UPLOADS_DIR}/{run_id}/{pmid}.pdf")
        db.set_retrieval_source(db_path, run_id, pmid, "prrc_upload", None)
        appraisal, status = _safe_appraise(
            db_path, run_id, rec,
            lambda: appraise_pdf(profile, rec, pdf_bytes, call=pdf_call))
        db.set_fulltext_appraisal(db_path, run_id, pmid, appraisal, status)
        results[pmid] = status
        progress(f"  appraised uploaded PMID {pmid}: {status}")
    db.log(db_path, run_id, "appraise_upload",
           f"upload-appraised {len(results)}: {results}")
    return results
