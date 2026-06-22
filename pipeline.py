"""
Vigil - CER Literature Review Assistant pipeline orchestrator (two-phase).

Phase A  (run_search_and_screen):
    Device Profile -> two-track PubMed search -> dedup -> abstract screen ->
    abstract-level extraction on included (flagged `appraisal_incomplete`) ->
    PRISMA + preliminary search report + preliminary CER draft.
    Produces a RETRIEVAL LIST: included papers awaiting full-text upload.

Phase B  (run_fulltext_appraisal):
    PRRC uploads full-text PDFs (pmid -> bytes) -> MEDDEV A6 appraisal on each ->
    papers upgrade `appraisal_incomplete` -> `complete` -> regenerate PRISMA,
    search report, and CER draft. Papers not uploaded stay flagged (auditable).

Each run is keyed to run_id + scope_hash for full audit traceability.
"""
from __future__ import annotations
import uuid

import config
import db
import pubmed
import clinicaltrials
import ris_ingest
import screen
import extract
import retrieve
import verify
import appraise
import prisma
import draft


def _build_outputs(db_path, run_id, profile, queries, duplicates):
    """Shared: derive PRISMA, build search report + CER draft, persist, return dict."""
    all_rows = db.get_records(db_path, run_id)
    counts = prisma.counts_from_run(all_rows, duplicates)
    prisma_svg = prisma.render_svg(counts, f"PRISMA 2020 - {profile.device_name}")
    search_report = draft.build_search_report(profile, queries, counts,
                                              prisma_svg, all_rows)
    pms_signals = db.get_cer_relevant_signals(db_path, profile.device_name)
    # The CER narrative is built from FULLY APPRAISED papers; abstract-only
    # (appraisal_incomplete) papers are listed separately and clearly flagged.
    appraised = db.get_records(
        db_path, run_id, "screen_verdict='include' AND appraisal_status='complete'")
    incomplete = db.get_records(
        db_path, run_id,
        "screen_verdict='include' AND appraisal_status='appraisal_incomplete'")
    cer_section = draft.build_cer_section(profile, appraised, incomplete, pms_signals)

    db.save_output(db_path, run_id, "search_report", search_report)
    db.save_output(db_path, run_id, "cer_draft", cer_section)
    db.save_output(db_path, run_id, "prisma_svg", prisma_svg)
    return {
        "run_id": run_id,
        "scope_hash": profile.run_scope_hash(),
        "queries": queries,
        "counts": counts.as_dict(),
        "search_report": search_report,
        "cer_section": cer_section,
        "prisma_svg": prisma_svg,
        "retrieval_list": db.retrieval_list(db_path, run_id),
        "manual_upload_list": db.manual_upload_list(db_path, run_id),
        "n_signals": len(pms_signals),
    }


def run_search_and_screen(profile, db_path=None, retmax=None,
                          comprehensive=False, include_ctgov=True,
                          ris_files=None, progress=lambda s: None):
    """Phase A. Returns a result dict including the retrieval_list for Phase B.

    comprehensive=False (default): top-N per track (retmax) - cheap, for demos/diagnostics.
    comprehensive=True: retrieve ALL hits per track up to config.MAX_HITS_PER_TRACK,
        paginated via the NCBI history server - the PRISMA-faithful path for a real CER.
    include_ctgov=True: also search ClinicalTrials.gov (trial registrations).
    ris_files: optional list of (path, source_label) for PRRC-uploaded subscription
        exports (e.g. Embase/Cochrane RIS). Ingested into the same dedup/screen pipeline.
    """
    db_path = db_path or config.DB_PATH
    retmax = retmax or config.DEFAULT_RETMAX_PER_TRACK
    run_id = f"{profile.device_name[:8].strip().replace(' ','_')}-{uuid.uuid4().hex[:8]}"

    db.init_db(db_path)
    db.start_run(db_path, run_id, profile)

    progress("Building two-track search queries from Device Profile...")
    queries = pubmed.build_track_queries(profile)

    search_meta = {}
    if comprehensive:
        progress("Track 1 (device-specific) - comprehensive retrieval (all hits)...")
        t1, m1 = pubmed.run_track_comprehensive(
            queries["device_specific"], "device_specific", progress=progress)
        progress(f"  Track 1: {len(t1)} records"
                 + (" (CAPPED)" if m1["capped"] else ""))
        progress("Track 2 (state of the art) - comprehensive retrieval (all hits)...")
        t2, m2 = pubmed.run_track_comprehensive(
            queries["state_of_art"], "state_of_art", progress=progress)
        progress(f"  Track 2: {len(t2)} records"
                 + (" (CAPPED)" if m2["capped"] else ""))
        search_meta = {"device_specific": m1, "state_of_art": m2}
    else:
        progress("Track 1 (device-specific) - searching PubMed...")
        t1 = pubmed.run_track(queries["device_specific"], "device_specific", retmax)
        progress(f"  Track 1: {len(t1)} records")
        progress("Track 2 (state of the art) - searching PubMed...")
        t2 = pubmed.run_track(queries["state_of_art"], "state_of_art", retmax)
        progress(f"  Track 2: {len(t2)} records")

    # --- ClinicalTrials.gov (second source: trial registrations, not papers) ---
    ctgov_records = []
    if include_ctgov:
        progress("ClinicalTrials.gov - searching trial registry (device-specific)...")
        try:
            ct_max = None if comprehensive else max(retmax, 20)
            ctgov_records, ct_meta = clinicaltrials.run_ctgov(
                profile, track_name="device_specific",
                max_hits=ct_max, progress=progress)
            progress(f"  ClinicalTrials.gov: {len(ctgov_records)} trial registrations"
                     + (" (CAPPED)" if ct_meta.get("capped") else ""))
            search_meta["clinicaltrials_gov"] = ct_meta
        except Exception as e:
            progress(f"  ClinicalTrials.gov search failed (continuing without it): {e}")
            search_meta["clinicaltrials_gov"] = {"error": str(e)}

    # --- PRRC-uploaded subscription exports (Embase/Cochrane/etc. via RIS) -------
    # The PRRC runs the search in their own subscription and uploads ONE export
    # file per source. Vigil ingests it into the same pipeline. The PRRC owns the
    # search strategy in those databases (a regulatory responsibility); Vigil only
    # parses what they export.
    ris_records = []
    if ris_files:
        for path, source_label in ris_files:
            try:
                recs, rmeta = ris_ingest.parse_ris_file(
                    path, source=source_label, track="device_specific")
                ris_records.extend(recs)
                progress(f"  {source_label}: ingested {rmeta['parsed']} references "
                         f"({rmeta['skipped_no_title']} skipped, no title)")
                search_meta[source_label] = rmeta
            except Exception as e:
                progress(f"  {source_label} ingest failed (continuing): {e}")
                search_meta[source_label] = {"error": str(e)}

    records, dups = pubmed.dedup(t1 + t2 + ctgov_records + ris_records)
    progress(f"Deduplicated: {len(records)} unique ({dups} duplicates removed)")

    # Cost circuit-breaker: screening bills one Sonnet call per record. In
    # non-comprehensive mode an unexpectedly large dedup set means something is
    # wrong (e.g. an accidental uncapped run); abort BEFORE any screening call
    # rather than silently spending $10-20. Comprehensive mode is a deliberate
    # opt-in and is exempt.
    if not comprehensive and len(records) > config.MAX_SCREEN_RECORDS:
        msg = (f"Aborting before screening: {len(records)} records exceed the "
               f"safety ceiling of {config.MAX_SCREEN_RECORDS} (non-comprehensive "
               f"mode). Refine the search to narrow scope, or set "
               f"VIGIL_COMPREHENSIVE=1 to run a deliberate comprehensive screen.")
        progress(msg)
        db.log(db_path, run_id, "abort", msg)
        raise RuntimeError(msg)

    for r in records:
        db.upsert_record(db_path, run_id, r)
    db.log(db_path, run_id, "search",
           f"t1={len(t1)} t2={len(t2)} ctgov={len(ctgov_records)} "
           f"ris={len(ris_records)} unique={len(records)} dups={dups}")

    progress("Screening abstracts for relevance (Claude Sonnet)...")
    screen.run(db_path, run_id, profile, db.get_records(db_path, run_id),
               progress=progress)

    included = db.get_records(db_path, run_id, "screen_verdict='include'")

    # Cost circuit-breaker: extraction bills one Sonnet call per included record.
    # In non-comprehensive mode an unexpectedly large include set means something is
    # wrong; abort BEFORE any extraction call rather than silently spending $10-20.
    # Comprehensive mode is a deliberate opt-in and is exempt.
    if not comprehensive and len(included) > config.MAX_EXTRACT_RECORDS:
        msg = (f"Aborting before extraction: {len(included)} included records exceed the "
               f"safety ceiling of {config.MAX_EXTRACT_RECORDS} (non-comprehensive "
               f"mode). Refine the search to narrow scope, or set "
               f"VIGIL_COMPREHENSIVE=1 to run a deliberate comprehensive extraction.")
        progress(msg)
        db.log(db_path, run_id, "abort", msg)
        raise RuntimeError(msg)

    progress(f"Abstract-level extraction on {len(included)} included papers "
             f"(flagged appraisal-incomplete until full text is appraised)...")
    extract.run(db_path, run_id, profile, included)

    # --- Auto full-text retrieval (open access) + verification + appraisal ---
    # Fetch every full text reachable for free (PMC, Unpaywall), VERIFY each
    # retrieved document is actually the paper we expect (DOI/title), and appraise
    # only the verified ones. Unverified or no-OA papers go to the PRRC upload list.
    if config.ENABLE_AUTO_RETRIEVAL:
        progress(f"Auto-retrieving open-access full text for {len(included)} papers "
                 f"(PMC + Unpaywall)...")
        retrieval = retrieve.retrieve_batch(included, progress=progress)

        progress("Verifying identity of retrieved documents (DOI / title)...")
        rec_by_pmid = {r["pmid"]: r for r in included}
        verified_retrieval = {}
        n_pass = n_fail = 0
        for pmid, res in retrieval.items():
            if res["kind"] is None:
                db.set_retrieval_source(db_path, run_id, pmid, "paywalled_manual", None)
                continue
            verdict = verify.verdict_for(rec_by_pmid[pmid], res)
            db.set_verification(db_path, run_id, pmid, verdict)
            if verdict["result"] in verify.VERIFIED:
                verified_retrieval[pmid] = res
                n_pass += 1
            else:
                # Found a copy but couldn't confirm identity -> do NOT appraise it.
                db.set_retrieval_source(db_path, run_id, pmid, "auto_unverified",
                                        res.get("source_url"))
                n_fail += 1
                progress(f"  PMID {pmid}: {verdict['result']} "
                         f"(score {verdict['score']}) -> routed to manual upload")
        progress(f"Verification: {n_pass} confirmed, {n_fail} unverified "
                 f"(routed to manual).")

        progress("Full-text appraisal on verified papers (Claude Opus)...")
        appraise.run_from_retrieval(db_path, run_id, profile, verified_retrieval,
                                    progress=progress)

    progress("Building outputs + manual-upload list...")
    out = _build_outputs(db_path, run_id, profile, queries, dups)
    out["_duplicates"] = dups  # carried for Phase B regeneration
    out["search_meta"] = search_meta  # comprehensive retrieval audit metadata
    n_manual = len(out["manual_upload_list"])
    n_auto = out["counts"]["included"]
    progress(f"Phase A done. Auto-appraised {n_auto} from open access; "
             f"{n_manual} paper(s) need a manual PRRC upload.")
    return out


def run_fulltext_appraisal(profile, run_id, uploads: dict, db_path=None,
                           duplicates=0, queries=None, progress=lambda s: None):
    """Phase B. uploads = {pmid: pdf_bytes}. Regenerates all outputs."""
    db_path = db_path or config.DB_PATH
    queries = queries or pubmed.build_track_queries(profile)

    progress(f"Full-text appraisal on {len(uploads)} uploaded paper(s) (Claude Opus)...")
    appraise.run_from_uploads(db_path, run_id, profile, uploads, progress=progress)

    progress("Regenerating PRISMA, search report, and CER draft...")
    out = _build_outputs(db_path, run_id, profile, queries, duplicates)
    still_incomplete = sum(
        1 for r in out["retrieval_list"] if r["appraisal_status"] == "appraisal_incomplete")
    progress(f"Phase B done. {out['counts']['included']} fully appraised; "
             f"{still_incomplete} still appraisal-incomplete.")
    return out


if __name__ == "__main__":
    from device_profile import DeviceProfile
    prof = DeviceProfile.from_json("devices/npwt_sample.json")
    out = run_search_and_screen(prof, progress=print)
    print("\n=== Phase A:", out["run_id"], "scope", out["scope_hash"], "===")
    print("Retrieval list (awaiting full text):")
    for r in out["retrieval_list"]:
        print(f"  [{r['appraisal_status']}] PMID {r['pmid']} - {r['title'][:70]}")
