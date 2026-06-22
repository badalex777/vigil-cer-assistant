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
import threading
import time

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

# --- cold-start DB wipe -------------------------------------------------------
# Streamlit re-runs the full script on EVERY interaction. Use a one-time sentinel
# so the deletion fires exactly once per browser session (the genuine cold start),
# not on every rerun where run_id happens to be None mid-session.
# Guard: never wipe if a run is already active in this session.
if not ss.get("_db_cleared"):
    if not ss.get("run_id"):
        try:
            os.remove(config.DB_PATH)
        except OSError:
            pass
    ss._db_cleared = True

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
ss.setdefault("_phase_a_thread", None)   # background thread for Phase A
ss.setdefault("_phase_a_result", None)   # shared result dict written by the thread
ss.setdefault("_cep_docx_bytes", None)   # cached CEP Word render (avoids per-rerun rebuild)
ss.setdefault("_docs_cache", None)       # cached step-6 doc set (built list + zip bytes)

# SAFETY: the default must be the CHEAP path, never comprehensive. If the env var is
# missing we cap at 250/track - a missing variable must never trigger a $20 run.
# Comprehensive (all hits) requires an EXPLICIT opt-in: VIGIL_COMPREHENSIVE=1.
_COMPREHENSIVE = os.getenv("VIGIL_COMPREHENSIVE", "0") == "1"
if _COMPREHENSIVE:
    DEMO_RETMAX = None   # comprehensive: retrieve all hits (the real-CER path)
else:
    DEMO_RETMAX = int(os.getenv("VIGIL_DEMO_RETMAX", "250") or "250")  # safe cap


def _run_phase_a_bg(profile, run_id, db_path, retmax, ris_uploads, result):
    """Run Phase A pipeline in a background thread, independent of Streamlit's execution.
    Writes output or error into the shared result dict when done.
    The main thread polls result['done'] via session state to know when to read the output.
    """
    prog = _make_progress_writer(result)
    try:
        result["progress"] = {"pct": 0.01, "msg": "Starting search..."}
        out = pipeline.run_search_and_screen(
            profile, db_path=db_path, retmax=retmax,
            comprehensive=(retmax is None), include_ctgov=True,
            progress=prog)
        if ris_uploads:
            for u in ris_uploads:
                for r in u["records"]:
                    db.upsert_record(db_path, run_id, r)
        result["output"] = out
    except Exception as e:
        result["error"] = str(e)
    finally:
        result["done"] = True


# Maps pipeline progress() string prefixes to (percentage, display message).
# Screening (50-78%) is handled per-paper inside _make_progress_writer.
_PHASE_A_STAGE_MAP = [
    ("Building two-track",                  0.02, "Building search queries from Device Profile..."),
    ("Track 1 (device-specific)",           0.05, "Searching PubMed - device-specific track..."),
    ("  Track 1:",                          0.22, "PubMed Track 1 complete. Starting Track 2..."),
    ("Track 2 (state of the art)",          0.24, "Searching PubMed - state of the art track..."),
    ("  Track 2:",                          0.38, "PubMed Track 2 complete."),
    ("ClinicalTrials.gov - search",         0.40, "Searching ClinicalTrials.gov..."),
    ("  ClinicalTrials.gov:",               0.45, "ClinicalTrials.gov complete."),
    ("Deduplicated",                        0.48, "Removing duplicates across all sources..."),
    ("Screening abstracts",                 0.50, "Screening abstracts for relevance (AI)..."),
    ("Abstract-level extraction",           0.78, "Extracting evidence from included papers..."),
    ("Auto-retrieving",                     0.83, "Retrieving open-access full texts..."),
    ("Verifying identity",                  0.90, "Verifying retrieved document identity..."),
    ("Verification:",                       0.92, "Verification complete."),
    ("Full-text appraisal on verified",     0.94, "Appraising full texts (Claude Opus)..."),
    ("Building outputs",                    0.98, "Building audit-ready document set..."),
    ("Phase A done",                        1.00, "Search and screening complete."),
]


def _make_progress_writer(result):
    """Returns a progress(str) callable that maps pipeline strings to (pct, msg)
    and writes them into result['progress'] for the UI fragment to read."""
    state = {"pct": 0.0}

    def _write(msg: str):
        pct = state["pct"]
        display = msg

        # Per-paper screening progress: "Screened N/M records"
        if msg.startswith("Screened "):
            try:
                parts = msg.split()
                done, total = int(parts[1].split("/")[0]), int(parts[1].split("/")[1])
                # Screening occupies 50-78% of the bar
                pct = 0.50 + (done / total) * 0.28
                display = f"Screening abstracts...  {done} / {total}"
            except Exception:
                pct = 0.52
                display = "Screening abstracts for relevance..."
        else:
            for prefix, stage_pct, stage_msg in _PHASE_A_STAGE_MAP:
                if msg.startswith(prefix) and stage_pct is not None:
                    if stage_pct >= state["pct"]:
                        pct = stage_pct
                        display = stage_msg
                    break

        state["pct"] = max(state["pct"], pct)
        result["progress"] = {"pct": min(state["pct"], 0.99), "msg": display}

    return _write


@st.fragment(run_every=2)
def _phase_a_progress_fragment():
    """Runs every 2 seconds independently - ONLY this block re-executes.
    The rest of the page (header, stepper, device profile, etc.) stays frozen.
    When the thread finishes, triggers a full app rerun to show the summary."""
    result = ss._phase_a_result or {}
    thread = ss._phase_a_thread

    # Thread done? Trigger full app rerun so step_research transitions to summary.
    if result.get("done") or (thread is not None and not thread.is_alive()):
        st.rerun(scope="app")
        return

    # One live status line, swapped server-side every 2s. No progress bar:
    # screening dominates wall-clock but maps to a narrow band, so a bar parks
    # at ~50% and reads as stuck on a recorded demo. A single honest status
    # line (incl. the live "Screening N/M" counter) advances visibly instead.
    # Rendered here in the fragment so exactly one message is ever on screen.
    msg = result.get("progress", {}).get("msg", "Starting...")
    st.markdown(f'<div class="livestatus">{msg}</div>', unsafe_allow_html=True)


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
    if ss.get("_readonly"):
        st.markdown('<div class="disclaimer"><b>Read-only view.</b> This run is locked; '
                    'the values below are the frozen scope and cannot be edited. Start a '
                    'new evaluation to change anything.</div>', unsafe_allow_html=True)
    st.markdown('<span class="muted">Define the device and the scope of the clinical '
                'evaluation. This scope is frozen when you lock the run, so it is fully '
                'auditable.</span>', unsafe_allow_html=True)
    d = ss.profile_dict or {}
    _ro = ss.get("_readonly", False)

    st.subheader("Device")
    ui_theme.section_note(
        "Identifies the device under evaluation and its risk class. The intended purpose "
        "and indications define the <b>scope</b> of the whole clinical evaluation (MEDDEV "
        "2.7/1 rev 4, Stage 0). Get this right: a scope that is too narrow misses relevant "
        "data; too broad pulls in noise. The classification (MDR Annex VIII) sets how much "
        "clinical evidence and scrutiny the Notified Body will expect.")
    c1, c2 = st.columns(2)
    device_name = c1.text_input("Device name", d.get("device_name", ""),
                                placeholder="e.g. PortaVac NPWT System", disabled=_ro)
    manufacturer = c2.text_input("Manufacturer", d.get("manufacturer", ""),
                                 placeholder="e.g. Acme Medical Devices Ltd", disabled=_ro)
    c3, c4 = st.columns(2)
    cls_opts = ["Class IIa", "Class IIb", "Class I", "Class III"]
    classification = c3.selectbox(
        "Classification", cls_opts,
        index=cls_opts.index(d.get("classification", "Class IIb"))
        if d.get("classification") in cls_opts else 1, disabled=_ro)
    classification_rule = c4.text_input("Classification rule (MDR Annex VIII)",
                                        d.get("classification_rule", ""),
                                        placeholder="e.g. Rule 11", disabled=_ro)
    device_description = st.text_area(
        "Device description", d.get("device_description", ""), height=80,
        placeholder="e.g. Portable single-use negative pressure wound therapy system "
        "delivering controlled sub-atmospheric pressure to the wound bed.", disabled=_ro)
    intended_purpose = st.text_area(
        "Intended purpose", d.get("intended_purpose", ""), height=80,
        placeholder="e.g. Promotion of wound healing in chronic and acute wounds via "
        "controlled negative pressure.", disabled=_ro)

    st.subheader("Clinical scope")
    ui_theme.section_note(
        "These drive the search. The medical condition and technology category build the "
        "<b>state-of-the-art (Track 2)</b> search; synonyms widen the <b>device-specific "
        "(Track 1)</b> search so relevant papers are not missed. Both tracks are required "
        "(MEDDEV A5.2). Be thorough here - an incomplete search is one of the most common "
        "reasons a CER is flagged at Notified Body review.")
    medical_condition = st.text_input("Medical condition(s) - comma separated",
                                      ", ".join(d.get("medical_condition", [])),
                                      placeholder="e.g. chronic wounds, diabetic foot ulcers", disabled=_ro)
    technology_category = st.text_input("Technology category - comma separated",
                                        ", ".join(d.get("technology_category", [])),
                                        placeholder="e.g. negative pressure wound therapy", disabled=_ro)
    therapeutic_area = st.text_input("Therapeutic area - comma separated",
                                     ", ".join(d.get("therapeutic_area", [])),
                                     placeholder="e.g. wound care, tissue viability", disabled=_ro)
    device_synonyms = st.text_input("Device synonyms / search terms - comma separated",
                                    ", ".join(d.get("device_synonyms", [])),
                                    placeholder="e.g. NPWT, vacuum-assisted closure, VAC", disabled=_ro)

    st.subheader("Review questions (PICO)")
    ui_theme.section_note(
        "PICO = <b>P</b>opulation, <b>I</b>ntervention, <b>C</b>omparator, "
        "<b>O</b>utcomes. It is the standard way to frame a focused, answerable clinical "
        "review question (MEDDEV A5.2). It structures the search and tells a reviewer "
        "exactly what clinical question the evidence is meant to answer.")
    cp1, cp2 = st.columns(2)
    pico_population = cp1.text_input("Population", d.get("pico_population", ""),
                                     placeholder="e.g. adults with chronic wounds", disabled=_ro)
    pico_intervention = cp2.text_input("Intervention", d.get("pico_intervention", ""),
                                       placeholder="e.g. negative pressure wound therapy", disabled=_ro)
    cp3, cp4 = st.columns(2)
    pico_comparator = cp3.text_input("Comparator", d.get("pico_comparator", ""),
                                     placeholder="e.g. standard wound dressings", disabled=_ro)
    pico_outcomes = cp4.text_input("Outcomes", d.get("pico_outcomes", ""),
                                   placeholder="e.g. wound healing rate, adverse events", disabled=_ro)

    st.subheader("Search limits")
    ui_theme.section_note(
        "The date range and languages bound the search. These limits are documented in "
        "the search protocol and report so the search is <b>reproducible</b> - a reviewer "
        "must be able to repeat it and get the same results (MEDDEV A5.3). Justify a "
        "narrow date range or a single language if you set one; restricting languages "
        "without justification can be challenged as a source of bias.")
    import datetime
    def _parse_date(s, default):
        try:
            return datetime.date.fromisoformat(str(s).replace("/", "-"))
        except (ValueError, AttributeError):
            return default
    cl1, cl2, cl3 = st.columns(3)
    date_from_d = cl1.date_input(
        "Date from", _parse_date(d.get("date_from", ""), datetime.date(2015, 1, 1)),
        min_value=datetime.date(1990, 1, 1), max_value=datetime.date.today(), disabled=_ro)
    date_to_d = cl2.date_input(
        "Date to", _parse_date(d.get("date_to", ""), datetime.date(2025, 12, 31)),
        min_value=datetime.date(1990, 1, 1), max_value=datetime.date.today(), disabled=_ro)
    lang_opts = ["English", "Spanish", "French", "German", "Italian", "Dutch",
                 "Portuguese", "Danish", "Swedish", "Norwegian", "Finnish"]
    languages_sel = cl3.multiselect(
        "Languages", lang_opts,
        default=d.get("languages", ["English"]) or ["English"], disabled=_ro)
    date_from = date_from_d.strftime("%Y/%m/%d")
    date_to = date_to_d.strftime("%Y/%m/%d")

    st.subheader("Selection criteria")
    ui_theme.section_note(
        "<b>What this is:</b> the rules that decide which papers from the search are kept "
        "and which are discarded - inclusion criteria (a paper must meet these to be "
        "included) and exclusion criteria (any of these removes it).<br>"
        "<b>Why it matters:</b> MEDDEV requires these to be fixed <b>before</b> you see "
        "the results. They are <b>locked at sign-off</b> (Step 3): once you lock the run "
        "they cannot change, and the audit trail proves they did not change between "
        "approval and the search. This prevents tuning the rules after the fact to favour "
        "convenient papers - a search must capture all relevant data, favourable AND "
        "unfavourable (MEDDEV 8.2).<br>"
        "<b>How to fill it:</b> one criterion per line. Track 1 (your device) and Track 2 "
        "(state of the art) can have different criteria, so they are entered separately.")
    t1inc = st.text_area("Track 1 (device-specific) - inclusion",
                         "\n".join(d.get("track1_inclusion_criteria",
                                         d.get("inclusion_criteria", []))), height=90,
                         placeholder="e.g. Human clinical study of the device or equivalent\n"
                         "Reports clinical safety or performance outcomes", disabled=_ro)
    t1exc = st.text_area("Track 1 (device-specific) - exclusion",
                         "\n".join(d.get("track1_exclusion_criteria",
                                         d.get("exclusion_criteria", []))), height=90,
                         placeholder="e.g. Animal or in vitro studies only\n"
                         "Non-English without translation", disabled=_ro)
    t2inc = st.text_area("Track 2 (state of the art) - inclusion",
                         "\n".join(d.get("track2_inclusion_criteria", [])), height=90,
                         placeholder="e.g. Characterises current standard of care for "
                         "the condition\nGuidelines or systematic reviews", disabled=_ro)
    t2exc = st.text_area("Track 2 (state of the art) - exclusion",
                         "\n".join(d.get("track2_exclusion_criteria", [])), height=90,
                         placeholder="e.g. Not relevant to the medical condition\n"
                         "Editorials or opinion pieces", disabled=_ro)

    st.subheader("Equivalence (MDCG 2020-5)")
    ui_theme.section_note(
        "Equivalence lets you use clinical data from another device to support yours. "
        "Under MDR it is demanding: the devices must be similar across <b>three</b> "
        "characteristics - technical, biological, and clinical (MDCG 2020-5) - and you "
        "must <b>disclose every difference</b> and justify why it does not affect clinical "
        "safety or performance. If the equivalent is made by another company, MDR normally "
        "requires a contract giving you ongoing access to its technical documentation. "
        "<b>Vigil assembles this comparison into the CER verbatim; it does not judge "
        "whether equivalence holds - that determination is yours.</b> You can claim more "
        "than one equivalent device.")
    equivalence_claimed = st.checkbox("Equivalence is claimed",
                                      value=d.get("equivalence_claimed", False), disabled=_ro)
    equivalent_devices = []
    if equivalence_claimed:
        # number of equivalents tracked in session; seed from existing profile
        if "n_equivalents" not in ss:
            existing = d.get("equivalent_devices", [])
            ss.n_equivalents = max(1, len(existing))
        existing = d.get("equivalent_devices", [])
        for i in range(ss.n_equivalents):
            eq = existing[i] if i < len(existing) else {}
            st.markdown(f'**Equivalent device {i + 1}**')
            eq_name = st.text_input("Equivalent device name", eq.get("name", ""),
                                    placeholder="e.g. VacuHeal Pro NPWT System",
                                    key=f"eq_name_{i}", disabled=_ro)
            eq_model = st.text_input("Equivalent device model/identifier",
                                     eq.get("model", ""), placeholder="e.g. VH-2000",
                                     key=f"eq_model_{i}", disabled=_ro)
            eq_tech = st.text_area("Technical characteristics - justification",
                                   eq.get("technical_characteristics", ""), height=80,
                                   placeholder="e.g. Same operating principle (controlled "
                                   "sub-atmospheric pressure), comparable pressure range.",
                                   key=f"eq_tech_{i}", disabled=_ro)
            eq_bio = st.text_area("Biological characteristics - justification",
                                  eq.get("biological_characteristics", ""), height=80,
                                  placeholder="e.g. Same wound-contacting materials; "
                                  "equivalent biocompatibility profile.", key=f"eq_bio_{i}", disabled=_ro)
            eq_clin = st.text_area("Clinical characteristics - justification",
                                   eq.get("clinical_characteristics", ""), height=80,
                                   placeholder="e.g. Same indication, population, and "
                                   "conditions of use.", key=f"eq_clin_{i}", disabled=_ro)
            eq_diff = st.text_area("Differences disclosed + justification (disclose ALL)",
                                   eq.get("differences_and_justification", ""), height=80,
                                   placeholder="e.g. Minor foam pore-size difference; not "
                                   "expected to affect clinical performance or safety.",
                                   key=f"eq_diff_{i}", disabled=_ro)
            eq_access = st.text_area("Access to the equivalent's technical documentation",
                                     eq.get("technical_documentation_access", ""),
                                     height=60, placeholder="e.g. Public IFU and published "
                                     "literature only - no contractual access to technical "
                                     "file.", key=f"eq_access_{i}", disabled=_ro)
            equivalent_devices.append({
                "name": eq_name, "model": eq_model,
                "technical_characteristics": eq_tech,
                "biological_characteristics": eq_bio,
                "clinical_characteristics": eq_clin,
                "differences_and_justification": eq_diff,
                "technical_documentation_access": eq_access,
            })
            st.markdown('<hr class="rule"/>', unsafe_allow_html=True)
        ceq1, ceq2 = st.columns([1, 1])
        if ceq1.button("+ Add another equivalent device", disabled=_ro):
            ss.n_equivalents += 1
            st.rerun()
        if ss.n_equivalents > 1 and ceq2.button("- Remove last equivalent device",
                                                 disabled=_ro):
            ss.n_equivalents -= 1
            st.rerun()

    st.subheader("Legacy device & update cycle")
    ui_theme.section_note(
        "A <b>legacy device</b> was CE-marked under the old directives (MDD/AIMDD) and is "
        "transitioning to MDR; it gets extra requirements under MDCG 2020-6. A "
        "<b>well-established technology (WET)</b> is a mature, stable, widely-used design "
        "with a long safety history (e.g. NPWT) - WET status can justify a less frequent "
        "update cycle. The CER is a living document: you set the <b>update interval</b> "
        "and must justify it by risk class and technology maturity (MDR Annex XIV); "
        "Notified Bodies check that justification.")
    cleg1, cleg2 = st.columns(2)
    is_legacy = cleg1.checkbox("Legacy device (MDD/AIMDD, MDR transition)",
                               value=d.get("is_legacy_device", False), disabled=_ro)
    is_wet = cleg2.checkbox("Well-established technology (WET)",
                            value=d.get("is_well_established_technology", False), disabled=_ro)
    next_interval = st.text_input("Next-evaluation interval (you define & justify)",
                                  d.get("next_evaluation_interval", ""),
                                  placeholder="e.g. 24 months", disabled=_ro)
    next_justif = st.text_area("Justification of the update interval",
                               d.get("next_evaluation_justification", ""), height=70,
                               placeholder="e.g. Well-established technology with a "
                               "stable design and continuous PMS monitoring that would "
                               "trigger an earlier update on any emerging signal.", disabled=_ro)
    req_evidence = alt_strategy = pms_strategy = ""
    if is_legacy:
        ui_theme.section_note(
            "These three fields are required for legacy devices (MDCG 2020-6 Appendix II):"
            "<br><b>Required level of clinical evidence</b> - <i>MDR Article 61(1)</i> says "
            "the manufacturer must define how much clinical evidence is enough for this "
            "specific device and its intended purpose. You state that level here."
            "<br><b>Alternative treatments strategy</b> - <i>MDR Article 61(3)(c)</i> "
            "requires you to identify and assess other available treatments for the "
            "condition, so the device is judged against the current standard of care."
            "<br><b>PMS data collection strategy</b> - how you systematically gather "
            "post-market surveillance data to show the device stays safe and performs "
            "over time (MDCG 2020-6).")
        req_evidence = st.text_area("Required level of clinical evidence (MDR Art. 61(1))",
                                    d.get("required_level_of_clinical_evidence", ""),
                                    height=60,
                                    placeholder="e.g. Cumulative appraised literature plus "
                                    "PMS data, to be confirmed sufficient by the PRRC.", disabled=_ro)
        alt_strategy = st.text_area(
            "Strategy to identify & assess alternative treatments (MDR Art. 61(3)(c))",
            d.get("alternative_treatments_strategy", ""), height=60,
            placeholder="e.g. Track 2 search plus clinical practice guidelines to "
            "benchmark against current standard of care.", disabled=_ro)
        pms_strategy = st.text_area("PMS data collection strategy (MDCG 2020-6)",
                                    d.get("pms_data_collection_strategy", ""), height=60,
                                    placeholder="e.g. Continuous signal monitoring via "
                                    "the Vigil PMS Monitor handoff feeding the CER cycle.", disabled=_ro)

    st.subheader("Evaluator")
    ui_theme.section_note(
        "The person who reviews and signs the CER. MDR and Notified Body practice require "
        "an evaluator with <b>clinical specialty relevant to the device's indication</b> "
        "- not regulatory-affairs staff alone. CERs have been rejected for lacking "
        "appropriate clinical input.<br><b>Declaration of interests reference</b>: the "
        "evaluator must declare any conflicts of interest (e.g. payment from, or a "
        "financial stake in, the manufacturer) in a separate signed document. This field "
        "just records a reference/ID to that document (e.g. a filename or code) so the CER "
        "can point to it - you do not write the declaration itself here.")
    ce1, ce2 = st.columns(2)
    evaluator_name = ce1.text_input("Evaluator name", d.get("evaluator_name", ""),
                                    placeholder="e.g. Dr. Jane Smith", disabled=_ro)
    evaluator_quals = ce2.text_input("Evaluator qualifications / clinical specialty",
                                     d.get("evaluator_qualifications", ""),
                                     placeholder="e.g. MD, wound care / tissue viability, "
                                     "8 yrs clinical experience", disabled=_ro)
    doi_ref = st.text_input("Declaration of interests reference (document ID, not the "
                            "declaration itself)",
                            d.get("declaration_of_interest_ref", ""),
                            placeholder="e.g. DOI-2026-001", disabled=_ro)

    st.markdown('<hr class="rule"/>', unsafe_allow_html=True)
    if _ro:
        st.markdown('<span class="muted">Read-only: changes cannot be saved on a locked '
                    'run.</span>', unsafe_allow_html=True)
        if st.button("Back to current step"):
            ss.step = 3 if ss.phase_a is None else (5 if ss.phase_b else 4)
            st.rerun()
        return
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
            "languages": languages_sel or ["English"],
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
    _ro = ss.get("_readonly", False)
    if _ro:
        st.markdown('<div class="disclaimer"><b>Read-only view.</b> These are the approved '
                    'search strings frozen for this locked run.</div>',
                    unsafe_allow_html=True)
    profile = _profile_from_state()
    if ss.queries is None:
        ss.queries = pubmed.build_track_queries(profile)

    st.markdown('<span class="muted">Vigil built these from the Device Profile. Review '
                'and edit; you approve the exact strings that run. Track 1 targets your '
                'device and any claimed equivalent; Track 2 the state of the art.</span>',
                unsafe_allow_html=True)
    t1 = st.text_area("Track 1 - device-specific (PubMed syntax)",
                      ss.queries["device_specific"], height=120, disabled=_ro)
    t2 = st.text_area("Track 2 - state of the art (PubMed syntax)",
                      ss.queries["state_of_art"], height=120, disabled=_ro)

    if _ro:
        st.markdown('<hr class="rule"/>', unsafe_allow_html=True)
        if st.button("Back to current step"):
            ss.step = 3 if ss.phase_a is None else (5 if ss.phase_b else 4)
            st.rerun()
        return

    if st.button("Preview hit counts"):
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
    profile = _profile_from_state()
    _is_locked_step = ss.run_id is not None

    st.header("3. Lock & Start")

    # ------------------------------------------------------------------
    # READ-ONLY: run is already locked - show what was committed.
    # ------------------------------------------------------------------
    if _is_locked_step:
        st.markdown('<div class="disclaimer"><b>Read-only view.</b> This run is locked. '
                    'The scope and databases below are frozen for this '
                    'evaluation.</div>', unsafe_allow_html=True)
        if ss.ris_uploads:
            st.markdown("**Subscription databases included in this run:**")
            for u in ss.ris_uploads:
                st.markdown(f"- **{u['source']}**: {u['n']} references "
                            + ("(query recorded)" if u.get("query", "").strip()
                               else "(no query recorded)"))
        else:
            st.markdown("_No subscription database exports were added for this run._")
        st.markdown('<hr class="rule"/>', unsafe_allow_html=True)
        if st.button("Back to current step"):
            ss.step = 3 if ss.phase_a is None else (5 if ss.phase_b else 4)
            st.rerun()
        return

    # ------------------------------------------------------------------
    # NORMAL: pre-lock flow
    # ------------------------------------------------------------------
    st.markdown('<div class="locknote">Locking freezes the scope and the approved search '
                'strings. After locking, the scope cannot change - this is what makes the '
                'evaluation auditable. The CEP is generated the moment you lock.</div>',
                unsafe_allow_html=True)

    st.subheader("Subscription databases (optional)")
    ui_theme.section_note(
        "<b>What this is:</b> PubMed and ClinicalTrials.gov are searched automatically. "
        "Embase and the Cochrane Library are subscription databases Vigil cannot connect "
        "to directly (their licences do not allow programmatic access), so if your search "
        "protocol includes them, you run that search yourself and add the results here."
        "<br><b>When you need it:</b> only if your CEP/search protocol commits to searching "
        "Embase or Cochrane. For many Class IIa/IIb devices PubMed + CT.gov is sufficient; "
        "the PRRC decides whether additional databases are required for completeness."
        "<br><b>How to do it:</b> (1) run your search in Embase/Cochrane; (2) export the "
        "results as an <b>RIS</b> file (every database has an Export &gt; RIS option); "
        "(3) upload that file below and paste the <b>exact</b> query string you ran. "
        "Vigil parses each reference into the same screening pipeline (dedup, screen, "
        "appraise) as PubMed."
        "<br><b>Why the exact query is mandatory:</b> it is written verbatim into the CEP "
        "and the search report so the search is reproducible and auditable. A search "
        "report that names a database without its query is an incomplete record and a "
        "common Notified Body finding.")
    with st.expander("Add a subscription-database export"):
        src = st.text_input("Source label (e.g. Embase, Cochrane)", key="ris_src")
        exact_q = st.text_area("Exact search string you ran in that database",
                               key="ris_q", height=80,
                               placeholder="e.g. ('negative pressure wound therapy'/exp OR "
                               "npwt) AND ('chronic wound'/exp) AND [2015-2025]/py")
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
        # Mark DB as running and launch background thread immediately.
        db.mark_running(config.DB_PATH, run_id, actor=actor)
        result = {"done": False, "output": None, "error": None,
                  "progress": {"pct": 0.01, "msg": "Starting search..."}}
        ss._phase_a_result = result
        t = threading.Thread(
            target=_run_phase_a_bg,
            args=(profile, run_id, config.DB_PATH, DEMO_RETMAX,
                  list(ss.ris_uploads), result),
            daemon=True)
        t.start()
        ss._phase_a_thread = t
        goto(3)  # go straight to Research in Progress
        st.rerun()


# =============================================================================
# STEP 4 - RESEARCH IN PROGRESS
# =============================================================================
def _show_orphaned_run_ui():
    """Show fail-clean recovery UI when Phase A thread died without completing."""
    st.error(
        "The previous run was interrupted (API error or crash). "
        "Results so far are incomplete and cannot be resumed."
    )
    if st.button("Start New Evaluation", type="primary"):
        import os
        try:
            os.remove(config.DB_PATH)
        except OSError:
            pass
        for k in ["step", "profile_dict", "queries", "counts_preview", "run_id",
                  "scope_hash", "phase_a", "phase_b", "cep_md", "ris_uploads",
                  "_phase_a_thread", "_phase_a_result", "n_equivalents",
                  "_cep_docx_bytes"]:
            ss.pop(k, None)
        st.rerun()


def step_research():
    st.header("4. Research in Progress")
    profile = _profile_from_state()

    # CEP always downloadable from the moment the run is locked.
    if ss.cep_md:
        import docx_export
        if ss._cep_docx_bytes is None:
            ss._cep_docx_bytes = docx_export.md_to_docx_bytes(
                ss.cep_md, "Clinical Evaluation Plan")
        st.download_button(
            "Download Clinical Evaluation Plan (CEP)", ss._cep_docx_bytes,
            file_name="01_Clinical_Evaluation_Plan.docx",
            mime=("application/vnd.openxmlformats-officedocument."
                  "wordprocessingml.document"))
        st.markdown('<span class="muted">Generated at lock, before any results - '
                    'it documents the planned scope.</span>', unsafe_allow_html=True)

    # ------------------------------------------------------------------ #
    # CASE 1: Phase A already done (result persisted in session).        #
    # ------------------------------------------------------------------ #
    if ss.phase_a is not None:
        out = ss.phase_a
        c = out["counts"]
        st.markdown(
            f'<div class="chips">'
            f'<div class="chip"><div class="k">Screened</div>'
            f'<div class="v">{c.get("screened", 0)}</div></div>'
            f'<div class="chip"><div class="k">Auto-appraised</div>'
            f'<div class="v">{c.get("included", 0)}</div></div>'
            f'<div class="chip"><div class="k">For upload</div>'
            f'<div class="v">{len(out["manual_upload_list"])}</div></div>'
            f'</div>', unsafe_allow_html=True)
        st.success("Phase A complete. Download the CEP above at any time.")
        if st.button("Continue to Phase B"):
            try:
                if db.current_state(config.DB_PATH, ss.run_id) == "running":
                    db.mark_phase_b(config.DB_PATH, ss.run_id,
                                    actor=profile.evaluator_name or "PRRC")
            except Exception:
                pass
            goto(4)
            st.rerun()
        return

    # ------------------------------------------------------------------ #
    # CASE 2: Background thread exists - check its state.                #
    # ------------------------------------------------------------------ #
    thread = ss._phase_a_thread
    result = ss._phase_a_result

    if thread is not None:
        if not thread.is_alive():
            # Thread just finished - collect the result on this run.
            if result and result.get("error"):
                _show_orphaned_run_ui()
                return
            if result and result.get("done") and result.get("output") is not None:
                ss.phase_a = result["output"]
                ss._phase_a_thread = None
                ss._phase_a_result = None
                st.rerun()
                return

        # Thread alive (or just finished but output not yet copied): show loading.
        # The card (spinner + honest time estimate) renders ONCE here; the
        # fragment below re-runs every 2s to swap a single live status line.
        load_box = st.empty()
        ui_theme.loading_card(
            load_box, "Searching",
            "This typically takes 5-20 minutes depending on how many papers match (longer for a comprehensive search).")
        _phase_a_progress_fragment()
        return

    # ------------------------------------------------------------------ #
    # CASE 3: No thread - orphaned if run was already locked              #
    # ------------------------------------------------------------------ #
    if ss.run_id is not None:
        _show_orphaned_run_ui()
        return
    st.info("The search has not started. Go back to step 3 and click "
            "'Lock scope & start research'.")


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
        load_box = st.empty()
        ui_theme.loading_card(
            load_box, "Appraising",
            "Appraising full texts with Claude Opus - this can take a few minutes.")

        def progress(s):
            pass  # Phase B blocks; the static card communicates the wait

        try:
            pb = pipeline.run_fulltext_appraisal(
                profile, ss.run_id, uploads, db_path=config.DB_PATH,
                duplicates=out.get("_duplicates", 0), queries=ss.queries,
                progress=progress)
            ss.phase_b = pb
            db.mark_complete(config.DB_PATH, ss.run_id,
                             actor=profile.evaluator_name or "PRRC")
        finally:
            load_box.empty()
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

    DOCX_MIME = ("application/vnd.openxmlformats-officedocument."
                 "wordprocessingml.document")

    if ss._docs_cache is None:
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

        # 5 narrative documents -> Word (.docx); audit trail stays CSV (data export)
        import docx_export
        word_docs = [
            ("01_Clinical_Evaluation_Plan.docx", cep, "Clinical Evaluation Plan"),
            ("02_Literature_Search_Protocol.docx", sp, "Literature Search Protocol"),
            ("03_Literature_Search_Report.docx", sr, "Literature Search Report"),
            ("04_CER_First_Draft.docx", cer, "CER First Draft"),
            ("05_Evidence_Traceability_Matrix.docx", tm, "Evidence Traceability Matrix"),
        ]

        built = []
        with st.spinner("Building Word documents..."):
            for fname, md, title in word_docs:
                data = docx_export.md_to_docx_bytes(md, title)
                built.append((fname, data, DOCX_MIME))
        built.append(("06_Audit_Trail.csv", audit.encode("utf-8"), "text/csv"))

        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
            for fname, data, _ in built:
                z.writestr(fname, data)

        ss._docs_cache = {"built": built, "zip": buf.getvalue()}

    st.markdown('<span class="muted">Six audit-ready documents, each carrying the same '
                'control block (run, scope hash, version) tying them to this immutable '
                'run. Five are Word documents for PRRC review and sign-off; the audit '
                'trail is a CSV data export.</span>', unsafe_allow_html=True)

    for fname, data, mime in ss._docs_cache["built"]:
        st.download_button(f"Download {fname}", data, file_name=fname, mime=mime,
                           key=f"dl_{fname}")

    st.download_button("Download all 6 documents (.zip)", ss._docs_cache["zip"],
                       file_name=f"Vigil_CER_set_{run_id}.zip", mime="application/zip")

    st.markdown('<hr class="rule"/>', unsafe_allow_html=True)
    if st.button("Start a new evaluation"):
        for k in ["step", "profile_dict", "queries", "counts_preview", "run_id",
                  "scope_hash", "phase_a", "phase_b", "cep_md", "ris_uploads",
                  "_phase_a_thread", "_phase_a_result", "_cep_docx_bytes",
                  "_docs_cache"]:
            ss.pop(k, None)
        st.rerun()


# =============================================================================
# ORCHESTRATION
# =============================================================================
ui_theme.header()
ui_theme.stepper(ss.step)

# Once a run is locked, the scope is frozen. Allow READ-ONLY navigation back to
# review what was entered, but ONLY to steps that are reachable (have data) - never
# forward into a step whose inputs do not exist yet.
_is_locked = ss.run_id is not None
if _is_locked:
    st.markdown('<div class="locknote">This run is <b>locked</b> - the scope is frozen '
                'and cannot be changed. You can review earlier steps in read-only mode. '
                'To change anything, start a new evaluation.</div>',
                unsafe_allow_html=True)
    # determine the furthest step the run has actually reached
    if ss.phase_b is not None:
        max_step = 5
    elif ss.phase_a is not None:
        max_step = 4   # Phase A done -> Phase B is available
    else:
        max_step = 3   # locked, search not yet run -> up to Research
    labels = ["1. Device Profile", "2. Search", "3. Lock", "4. Research", "5. Phase B", "6. Docs"]
    reachable = [i for i in range(6) if i <= max_step]
    nav = st.columns(len(reachable))
    for col, i in zip(nav, reachable):
        if col.button(labels[i], key=f"nav_{i}"):
            ss.step = i
            st.rerun()

ss.setdefault("_readonly", False)
ss._readonly = _is_locked and ss.step in (0, 1)  # steps 1-2 are read-only once locked

_STEPS = [step_device_profile, step_review_search, step_lock_and_start,
          step_research, step_phase_b, step_documents]
_STEPS[ss.step]()
