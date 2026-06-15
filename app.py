"""
Vigil - CER Literature Review Assistant. Demo wizard (Streamlit).

Run:  streamlit run app.py
Env:  ANTHROPIC_API_KEY (required); NCBI_API_KEY / NCBI_EMAIL (optional);
      VIGIL_DEMO_RETMAX (optional, INTERNAL: caps per-track hits for cheap testing -
      NOT shown in the UI; the product always runs comprehensive for the user).

Six steps, mapped to the run state machine:
  1 Device Profile          (draft)
  2 Review & Approve Search (draft -> strings_approved)   + free count preview
  3 Lock & Start            (strings_approved -> locked)  -> CEP downloads at lock
  4 Research in Progress    (locked -> running)           PubMed + CT.gov + screen + appraise
  5 Phase B - Manual Upload (running -> phase_b)          paywalled PDFs + subscription RIS
  6 Document Set            (phase_b -> complete)         the 6 auditable documents
"""
import os
import io
import zipfile

import streamlit as st

import config
import db
import pubmed
import outputs
import pipeline
from device_profile import DeviceProfile
import ui_theme

st.set_page_config(page_title="Vigil - CER Assistant", layout="centered",
                   initial_sidebar_state="collapsed")
ui_theme.inject()
ss = st.session_state

# --- session defaults --------------------------------------------------------
ss.setdefault("step", 0)
ss.setdefault("profile_dict", None)
ss.setdefault("queries", None)
ss.setdefault("counts_preview", None)
ss.setdefault("run_id", None)
ss.setdefault("scope_hash", None)
ss.setdefault("phase_a", None)
ss.setdefault("phase_b", None)
ss.setdefault("cep_md", None)
ss.setdefault("ris_uploads", [])

DEMO_RETMAX = int(os.getenv("VIGIL_DEMO_RETMAX", "0")) or None  # internal; 0 = comprehensive


def goto(step):
    ss.step = step


def _profile_from_state() -> DeviceProfile:
    return DeviceProfile.from_dict(ss.profile_dict)


def _split(s):
    return [x.strip() for x in s.replace("\n", ",").split(",") if x.strip()]


def _lines(s):
    return [x.strip() for x in s.split("\n") if x.strip()]


# =============================================================================
# STEP 1 - DEVICE PROFILE (hybrid)
# =============================================================================
def step_device_profile():
    st.header("1. Device Profile")
    st.markdown('<span class="muted">Define the device and the scope of the clinical '
                'evaluation. This scope is frozen when you lock the run, so it is fully '
                'auditable.</span>', unsafe_allow_html=True)
    d = ss.profile_dict or {}

    st.subheader("Device")
    c1, c2 = st.columns(2)
    device_name = c1.text_input("Device name", d.get("device_name", ""),
                                placeholder="e.g. PortaVac NPWT System")
    manufacturer = c2.text_input("Manufacturer", d.get("manufacturer", ""),
                                 placeholder="e.g. Acme Medical Devices Ltd")
    c3, c4 = st.columns(2)
    cls_opts = ["Class IIa", "Class IIb", "Class I", "Class III"]
    classification = c3.selectbox(
        "Classification", cls_opts,
        index=cls_opts.index(d.get("classification", "Class IIb"))
        if d.get("classification") in cls_opts else 1)
    classification_rule = c4.text_input("Classification rule (MDR Annex VIII)",
                                        d.get("classification_rule", ""),
                                        placeholder="e.g. Rule 11")
    device_description = st.text_area(
        "Device description", d.get("device_description", ""), height=80,
        placeholder="e.g. Portable single-use negative pressure wound therapy system "
        "delivering controlled sub-atmospheric pressure to the wound bed.")
    intended_purpose = st.text_area(
        "Intended purpose", d.get("intended_purpose", ""), height=80,
        placeholder="e.g. Promotion of wound healing in chronic and acute wounds via "
        "controlled negative pressure.")

    st.subheader("Clinical scope")
    medical_condition = st.text_input("Medical condition(s) - comma separated",
                                      ", ".join(d.get("medical_condition", [])),
                                      placeholder="e.g. chronic wounds, diabetic foot ulcers")
    technology_category = st.text_input("Technology category - comma separated",
                                        ", ".join(d.get("technology_category", [])),
                                        placeholder="e.g. negative pressure wound therapy")
    therapeutic_area = st.text_input("Therapeutic area - comma separated",
                                     ", ".join(d.get("therapeutic_area", [])),
                                     placeholder="e.g. wound care, tissue viability")
    device_synonyms = st.text_input("Device synonyms / search terms - comma separated",
                                    ", ".join(d.get("device_synonyms", [])),
                                    placeholder="e.g. NPWT, vacuum-assisted closure, VAC")

    st.subheader("Review questions (PICO)")
    cp1, cp2 = st.columns(2)
    pico_population = cp1.text_input("Population", d.get("pico_population", ""),
                                     placeholder="e.g. adults with chronic wounds")
    pico_intervention = cp2.text_input("Intervention", d.get("pico_intervention", ""),
                                       placeholder="e.g. negative pressure wound therapy")
    cp3, cp4 = st.columns(2)
    pico_comparator = cp3.text_input("Comparator", d.get("pico_comparator", ""),
                                     placeholder="e.g. standard wound dressings")
    pico_outcomes = cp4.text_input("Outcomes", d.get("pico_outcomes", ""),
                                   placeholder="e.g. wound healing rate, adverse events")

    st.subheader("Search limits")
    cl1, cl2, cl3 = st.columns(3)
    date_from = cl1.text_input("Date from (YYYY/MM/DD)", d.get("date_from", "2015/01/01"))
    date_to = cl2.text_input("Date to (YYYY/MM/DD)", d.get("date_to", "2025/12/31"))
    languages = cl3.text_input("Languages", ", ".join(d.get("languages", ["English"])))

    st.subheader("Selection criteria")
    st.markdown('<span class="muted">Locked at sign-off. One per line, per track.</span>',
                unsafe_allow_html=True)
    t1inc = st.text_area("Track 1 (device-specific) - inclusion",
                         "\n".join(d.get("track1_inclusion_criteria",
                                         d.get("inclusion_criteria", []))), height=90,
                         placeholder="e.g. Human clinical study of the device or equivalent\n"
                         "Reports clinical safety or performance outcomes")
    t1exc = st.text_area("Track 1 (device-specific) - exclusion",
                         "\n".join(d.get("track1_exclusion_criteria",
                                         d.get("exclusion_criteria", []))), height=90,
                         placeholder="e.g. Animal or in vitro studies only\n"
                         "Non-English without translation")
    t2inc = st.text_area("Track 2 (state of the art) - inclusion",
                         "\n".join(d.get("track2_inclusion_criteria", [])), height=90,
                         placeholder="e.g. Characterises current standard of care for "
                         "the condition\nGuidelines or systematic reviews")
    t2exc = st.text_area("Track 2 (state of the art) - exclusion",
                         "\n".join(d.get("track2_exclusion_criteria", [])), height=90,
                         placeholder="e.g. Not relevant to the medical condition\n"
                         "Editorials or opinion pieces")

    st.subheader("Equivalence (MDCG 2020-5)")
    equivalence_claimed = st.checkbox("Equivalence is claimed",
                                      value=d.get("equivalence_claimed", False))
    equivalent_devices = []
    if equivalence_claimed:
        existing = d.get("equivalent_devices", [{}])
        eq = existing[0] if existing else {}
        st.markdown('<span class="muted">Vigil assembles this into the CER verbatim and '
                    'does not judge whether equivalence holds - that is your '
                    'determination.</span>', unsafe_allow_html=True)
        eq_name = st.text_input("Equivalent device name", eq.get("name", ""),
                                placeholder="e.g. VacuHeal Pro NPWT System")
        eq_model = st.text_input("Equivalent device model/identifier", eq.get("model", ""),
                                 placeholder="e.g. VH-2000")
        eq_tech = st.text_area("Technical characteristics - justification",
                               eq.get("technical_characteristics", ""), height=80,
                               placeholder="e.g. Same operating principle (controlled "
                               "sub-atmospheric pressure), comparable pressure range.")
        eq_bio = st.text_area("Biological characteristics - justification",
                              eq.get("biological_characteristics", ""), height=80,
                              placeholder="e.g. Same wound-contacting materials; "
                              "equivalent biocompatibility profile.")
        eq_clin = st.text_area("Clinical characteristics - justification",
                               eq.get("clinical_characteristics", ""), height=80,
                               placeholder="e.g. Same indication, population, and "
                               "conditions of use.")
        eq_diff = st.text_area("Differences disclosed + justification (disclose ALL)",
                               eq.get("differences_and_justification", ""), height=80,
                               placeholder="e.g. Minor foam pore-size difference; not "
                               "expected to affect clinical performance or safety.")
        eq_access = st.text_area("Access to the equivalent's technical documentation",
                                 eq.get("technical_documentation_access", ""), height=60,
                                 placeholder="e.g. Public IFU and published literature "
                                 "only - no contractual access to technical file.")
        equivalent_devices = [{
            "name": eq_name, "model": eq_model,
            "technical_characteristics": eq_tech,
            "biological_characteristics": eq_bio,
            "clinical_characteristics": eq_clin,
            "differences_and_justification": eq_diff,
            "technical_documentation_access": eq_access,
        }]

    st.subheader("Legacy device & update cycle")
    cleg1, cleg2 = st.columns(2)
    is_legacy = cleg1.checkbox("Legacy device (MDD/AIMDD, MDR transition)",
                               value=d.get("is_legacy_device", False))
    is_wet = cleg2.checkbox("Well-established technology (WET)",
                            value=d.get("is_well_established_technology", False))
    next_interval = st.text_input("Next-evaluation interval (you define & justify)",
                                  d.get("next_evaluation_interval", ""),
                                  placeholder="e.g. 24 months")
    next_justif = st.text_area("Justification of the update interval",
                               d.get("next_evaluation_justification", ""), height=70,
                               placeholder="e.g. Well-established technology with a "
                               "stable design and continuous PMS monitoring that would "
                               "trigger an earlier update on any emerging signal.")
    req_evidence = alt_strategy = pms_strategy = ""
    if is_legacy:
        req_evidence = st.text_area("Required level of clinical evidence (MDR Art. 61(1))",
                                    d.get("required_level_of_clinical_evidence", ""),
                                    height=60,
                                    placeholder="e.g. Cumulative appraised literature plus "
                                    "PMS data, to be confirmed sufficient by the PRRC.")
        alt_strategy = st.text_area(
            "Strategy to identify & assess alternative treatments (MDR Art. 61(3)(c))",
            d.get("alternative_treatments_strategy", ""), height=60,
            placeholder="e.g. Track 2 search plus clinical practice guidelines to "
            "benchmark against current standard of care.")
        pms_strategy = st.text_area("PMS data collection strategy (MDCG 2020-6)",
                                    d.get("pms_data_collection_strategy", ""), height=60,
                                    placeholder="e.g. Continuous signal monitoring via "
                                    "the Vigil PMS Monitor handoff feeding the CER cycle.")

    st.subheader("Evaluator")
    st.markdown('<span class="muted">Must have clinical specialty relevant to the '
                'device\'s indication - not regulatory-affairs staff alone.</span>',
                unsafe_allow_html=True)
    ce1, ce2 = st.columns(2)
    evaluator_name = ce1.text_input("Evaluator name", d.get("evaluator_name", ""),
                                    placeholder="e.g. Dr. Jane Smith")
    evaluator_quals = ce2.text_input("Evaluator qualifications / clinical specialty",
                                     d.get("evaluator_qualifications", ""),
                                     placeholder="e.g. MD, wound care / tissue viability, "
                                     "8 yrs clinical experience")
    doi_ref = st.text_input("Declaration of interests reference",
                            d.get("declaration_of_interest_ref", ""),
                            placeholder="e.g. DOI-2026-001")

    st.markdown('<hr class="rule"/>', unsafe_allow_html=True)
    if st.button("Save profile and continue"):
        if not device_name.strip():
            st.error("Device name is required.")
            return
        ss.profile_dict = {
            "device_name": device_name, "manufacturer": manufacturer,
            "device_description": device_description,
            "intended_purpose": intended_purpose,
            "classification": classification, "classification_rule": classification_rule,
            "device_synonyms": _split(device_synonyms), "comparator_devices": [],
            "medical_condition": _split(medical_condition),
            "technology_category": _split(technology_category),
            "therapeutic_area": _split(therapeutic_area),
            "date_from": date_from, "date_to": date_to,
            "languages": _split(languages) or ["English"],
            "track1_inclusion_criteria": _lines(t1inc),
            "track1_exclusion_criteria": _lines(t1exc),
            "track2_inclusion_criteria": _lines(t2inc),
            "track2_exclusion_criteria": _lines(t2exc),
            "inclusion_criteria": _lines(t1inc), "exclusion_criteria": _lines(t1exc),
            "equivalence_claimed": equivalence_claimed,
            "equivalent_devices": equivalent_devices, "manufacturer_claims": [],
            "pico_population": pico_population, "pico_intervention": pico_intervention,
            "pico_comparator": pico_comparator, "pico_outcomes": pico_outcomes,
            "relevant_gspr": d.get("relevant_gspr", []),
            "is_legacy_device": is_legacy,
            "is_well_established_technology": is_wet,
            "required_level_of_clinical_evidence": req_evidence,
            "alternative_treatments_strategy": alt_strategy,
            "pms_data_collection_strategy": pms_strategy,
            "next_evaluation_interval": next_interval,
            "next_evaluation_justification": next_justif,
            "evaluator_name": evaluator_name,
            "evaluator_qualifications": evaluator_quals,
            "declaration_of_interest_ref": doi_ref,
        }
        ss.queries = None
        goto(1)
        st.rerun()


# =============================================================================
# STEP 2 - REVIEW & APPROVE SEARCH
# =============================================================================
def step_review_search():
    st.header("2. Review & Approve Search")
    profile = _profile_from_state()
    if ss.queries is None:
        ss.queries = pubmed.build_track_queries(profile)

    st.markdown('<span class="muted">Vigil built these from the Device Profile. Review '
                'and edit; you approve the exact strings that run. Track 1 targets your '
                'device and any claimed equivalent; Track 2 the state of the art.</span>',
                unsafe_allow_html=True)
    t1 = st.text_area("Track 1 - device-specific (PubMed syntax)",
                      ss.queries["device_specific"], height=120)
    t2 = st.text_area("Track 2 - state of the art (PubMed syntax)",
                      ss.queries["state_of_art"], height=120)

    if st.button("Preview hit counts (free - no cost)"):
        ss.queries = {"device_specific": t1, "state_of_art": t2}
        with st.spinner("Querying PubMed for counts..."):
            try:
                ss.counts_preview = {"t1": pubmed.esearch_count(t1),
                                     "t2": pubmed.esearch_count(t2)}
            except Exception as e:
                st.error(f"Count preview failed: {e}")

    if ss.counts_preview:
        n1, n2 = ss.counts_preview["t1"], ss.counts_preview["t2"]
        st.markdown(
            f'<div class="chips">'
            f'<div class="chip"><div class="k">Track 1 hits</div><div class="v">{n1}</div></div>'
            f'<div class="chip"><div class="k">Track 2 hits</div><div class="v">{n2}</div></div>'
            f'<div class="chip"><div class="k">Combined</div><div class="v">{n1 + n2}</div></div>'
            f'</div>', unsafe_allow_html=True)
        st.markdown('<span class="muted">These are the records the comprehensive search '
                    'will retrieve and screen. Refine the strings before approving if the '
                    'count is very large.</span>', unsafe_allow_html=True)

    st.markdown('<hr class="rule"/>', unsafe_allow_html=True)
    cc1, cc2 = st.columns(2)
    if cc1.button("Back to profile"):
        goto(0)
        st.rerun()
    if cc2.button("Approve these search strings"):
        ss.queries = {"device_specific": t1, "state_of_art": t2}
        goto(2)
        st.rerun()


# =============================================================================
# STEP 3 - LOCK & START
# =============================================================================
def step_lock_and_start():
    st.header("3. Lock & Start")
    profile = _profile_from_state()
    st.markdown('<div class="locknote">Locking freezes the scope and the approved search '
                'strings. After locking, the scope cannot change - this is what makes the '
                'evaluation auditable. The CEP is generated the moment you lock.</div>',
                unsafe_allow_html=True)

    st.subheader("Subscription databases (optional)")
    st.markdown('<span class="muted">If you have Embase or Cochrane access, run the '
                'equivalent search in your own subscription, export as RIS, and add it '
                'here. Paste the EXACT query you ran - it is recorded in the CEP and '
                'search report. Vigil cannot connect to these databases directly (their '
                'licences do not permit it), so you own and run that search.</span>',
                unsafe_allow_html=True)
    with st.expander("Add a subscription-database export"):
        src = st.text_input("Source label (e.g. Embase, Cochrane)", key="ris_src")
        exact_q = st.text_area("Exact search string you ran in that database",
                               key="ris_q", height=80)
        ris_file = st.file_uploader("RIS export file", type=["ris", "txt"], key="ris_file")
        if st.button("Add this export"):
            if ris_file and src.strip():
                import ris_ingest
                text = ris_file.getvalue().decode("utf-8", errors="replace")
                recs, meta = ris_ingest.parse_ris(text, source=src.strip().lower())
                ss.ris_uploads.append({"source": src.strip(), "query": exact_q,
                                       "records": recs, "n": len(recs)})
                st.success(f"Added {len(recs)} references from {src}.")
            else:
                st.error("Provide a source label and an RIS file.")
    for u in ss.ris_uploads:
        st.markdown(f"- **{u['source']}**: {u['n']} references "
                    + ("(query recorded)" if u["query"].strip()
                       else "(no query recorded - add it for the audit trail)"))

    st.markdown('<hr class="rule"/>', unsafe_allow_html=True)
    cc1, cc2 = st.columns(2)
    if cc1.button("Back to search"):
        goto(1)
        st.rerun()
    if cc2.button("Lock scope & start research"):
        run_id = f"{profile.device_name[:8].strip().replace(' ', '_')}-{os.urandom(4).hex()}"
        ss.run_id = run_id
        ss.scope_hash = profile.run_scope_hash()
        db.init_db(config.DB_PATH)
        actor = profile.evaluator_name or "PRRC"
        db.init_run_state(config.DB_PATH, run_id, actor=actor)
        db.approve_strings(config.DB_PATH, run_id, ss.queries, actor=actor)
        db.lock_run(config.DB_PATH, run_id, ss.scope_hash, actor=actor)
        ss.cep_md = outputs.generate_cep_md(profile, run_id, approved_queries=ss.queries,
                                            scope_hash=ss.scope_hash)
        goto(3)
        st.rerun()


# =============================================================================
# STEP 4 - RESEARCH IN PROGRESS
# =============================================================================
def step_research():
    st.header("4. Research in Progress")
    profile = _profile_from_state()

    if ss.cep_md:
        st.download_button("Download Clinical Evaluation Plan (CEP)", ss.cep_md,
                           file_name="01_Clinical_Evaluation_Plan.md",
                           mime="text/markdown")
        st.markdown('<span class="muted">The CEP was generated at lock, before any '
                    'results - it documents the planned scope.</span>',
                    unsafe_allow_html=True)

    if ss.phase_a is None:
        st.markdown('<div class="locknote">Running comprehensive retrieval across PubMed '
                    'and ClinicalTrials.gov, then abstract screening. This can take '
                    'several minutes on a full search.</div>', unsafe_allow_html=True)
        if st.button("Run Phase A (search + screen)"):
            log_box = st.empty()
            lines = []

            def progress(s):
                lines.append(s)
                log_box.code("\n".join(lines[-16:]))

            db.mark_running(config.DB_PATH, ss.run_id,
                            actor=profile.evaluator_name or "PRRC")
            with st.spinner("Phase A running..."):
                out = pipeline.run_search_and_screen(
                    profile, db_path=config.DB_PATH, retmax=DEMO_RETMAX,
                    comprehensive=(DEMO_RETMAX is None), include_ctgov=True,
                    progress=progress)
                if ss.ris_uploads:
                    merged = 0
                    for u in ss.ris_uploads:
                        for r in u["records"]:
                            db.upsert_record(config.DB_PATH, ss.run_id, r)
                            merged += 1
                    progress(f"Merged {merged} subscription-database references.")
            ss.phase_a = out
            st.rerun()
    else:
        out = ss.phase_a
        c = out["counts"]
        st.markdown(
            f'<div class="chips">'
            f'<div class="chip"><div class="k">Screened</div><div class="v">{c.get("screened",0)}</div></div>'
            f'<div class="chip"><div class="k">Auto-appraised</div><div class="v">{c.get("included",0)}</div></div>'
            f'<div class="chip"><div class="k">For upload</div><div class="v">{len(out["manual_upload_list"])}</div></div>'
            f'</div>', unsafe_allow_html=True)
        st.success("Phase A complete. Open-access papers were retrieved and appraised.")
        if st.button("Continue to Phase B"):
            db.mark_phase_b(config.DB_PATH, ss.run_id,
                            actor=profile.evaluator_name or "PRRC")
            goto(4)
            st.rerun()


# =============================================================================
# STEP 5 - PHASE B
# =============================================================================
def step_phase_b():
    st.header("5. Phase B - Manual Upload")
    profile = _profile_from_state()
    out = ss.phase_a
    manual = out["manual_upload_list"]

    st.markdown('<span class="muted">These included papers had no open-access full text. '
                'Upload the PDF for any you can access; appraisal runs on what you upload. '
                'Uploading is optional - any paper left without full text is flagged '
                '\'appraisal incomplete\' in the CER, never silently treated as '
                'appraised.</span>', unsafe_allow_html=True)

    uploads = {}
    if not manual:
        st.success("No paywalled residuals - every included paper was retrieved open "
                   "access.")
    else:
        st.write(f"{len(manual)} paper(s) need a full-text PDF:")
        for r in manual:
            pmid = r.get("pmid") or r.get("registry_id") or r.get("external_id")
            f = st.file_uploader(f"[{pmid}] {r.get('title', '')[:90]}",
                                 type=["pdf"], key=f"pdf_{pmid}")
            if f is not None:
                uploads[pmid] = f.getvalue()

    st.markdown('<hr class="rule"/>', unsafe_allow_html=True)
    label = "Run full-text appraisal & build documents" if manual else \
            "Build the document set"
    if st.button(label):
        log_box = st.empty()
        lines = []

        def progress(s):
            lines.append(s)
            log_box.code("\n".join(lines[-16:]))

        with st.spinner("Phase B running (full-text appraisal via Opus)..."):
            pb = pipeline.run_fulltext_appraisal(
                profile, ss.run_id, uploads, db_path=config.DB_PATH,
                duplicates=out.get("_duplicates", 0), queries=ss.queries,
                progress=progress)
        ss.phase_b = pb
        db.mark_complete(config.DB_PATH, ss.run_id,
                         actor=profile.evaluator_name or "PRRC")
        goto(5)
        st.rerun()


# =============================================================================
# STEP 6 - DOCUMENT SET
# =============================================================================
def step_documents():
    st.header("6. Document Set")
    profile = _profile_from_state()
    out = ss.phase_b or ss.phase_a
    run_id, scope_hash = ss.run_id, ss.scope_hash
    ui_theme.disclaimer()

    counts = out["counts"]
    search_meta = ss.phase_a.get("search_meta", {}) if ss.phase_a else {}
    records = db.retrieval_list(config.DB_PATH, run_id)
    appraised = [r for r in records if r.get("appraisal_status") == "complete"]
    incomplete = [r for r in records if r.get("appraisal_status") == "appraisal_incomplete"]

    from prisma import PrismaCounts
    if hasattr(counts, "as_dict"):
        pc = counts
    else:
        pc = PrismaCounts(**{k: counts.get(k, 0) for k in [
            "db_records", "register_records", "duplicates_removed", "screened",
            "excluded_screening", "reports_sought", "reports_not_retrieved",
            "assessed", "excluded_eligibility", "included"]})

    cep = ss.cep_md or outputs.generate_cep_md(profile, run_id, ss.queries, scope_hash)
    sp = outputs.generate_search_protocol_md(
        profile, run_id, ss.queries, scope_hash,
        ris_sources=[u["source"] for u in ss.ris_uploads] or None)
    sr = outputs.generate_search_report_md(profile, run_id, pc, search_meta,
                                           scope_hash=scope_hash)
    tm = outputs.generate_traceability_matrix_md(profile, run_id, records,
                                                 scope_hash=scope_hash)
    log_rows = db.get_run_log(config.DB_PATH, run_id) if hasattr(db, "get_run_log") else []
    state_row = db.get_run_state(config.DB_PATH, run_id)
    audit = outputs.generate_audit_trail_csv(log_rows, state_row)
    cer = outputs.generate_cer_md(profile, run_id, appraised, incomplete,
                                  pms_signals=[], counts=pc, scope_hash=scope_hash)

    docs = [
        ("01_Clinical_Evaluation_Plan.md", cep),
        ("02_Literature_Search_Protocol.md", sp),
        ("03_Literature_Search_Report.md", sr),
        ("04_CER_First_Draft.md", cer),
        ("05_Evidence_Traceability_Matrix.md", tm),
        ("06_Audit_Trail.csv", audit),
    ]

    st.markdown('<span class="muted">Six audit-ready documents, each carrying the same '
                'control block (run, scope hash, version) tying them to this immutable '
                'run. All are first drafts for PRRC review and sign-off.</span>',
                unsafe_allow_html=True)
    for name, content in docs:
        st.download_button(f"Download {name}", content, file_name=name,
                           mime="text/csv" if name.endswith(".csv") else "text/markdown",
                           key=f"dl_{name}")

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for name, content in docs:
            z.writestr(name, content)
    st.download_button("Download all 6 documents (.zip)", buf.getvalue(),
                       file_name=f"Vigil_CER_set_{run_id}.zip", mime="application/zip")

    st.markdown('<hr class="rule"/>', unsafe_allow_html=True)
    if st.button("Start a new evaluation"):
        for k in ["step", "profile_dict", "queries", "counts_preview", "run_id",
                  "scope_hash", "phase_a", "phase_b", "cep_md", "ris_uploads"]:
            ss.pop(k, None)
        st.rerun()


# =============================================================================
# ORCHESTRATION
# =============================================================================
ui_theme.header()
ui_theme.stepper(ss.step)
_STEPS = [step_device_profile, step_review_search, step_lock_and_start,
          step_research, step_phase_b, step_documents]
_STEPS[ss.step]()
