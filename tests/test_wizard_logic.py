"""
Vigil - wizard logic tests (no Streamlit, no network, no Opus).

The Streamlit UI itself can only be exercised by running it, but the LOGIC behind
each step is plain Python and must be correct before a live demo:
  - a form-style dict builds a valid DeviceProfile (hybrid form output),
  - the run state machine drives draft -> approved -> locked correctly,
  - get_run_log returns the event log for the audit trail,
  - the full six-document set generates end-to-end from that profile.

Run: python tests/test_wizard_logic.py
"""
import io
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import db
import outputs
import pubmed
from device_profile import DeviceProfile
from prisma import PrismaCounts


# A dict shaped exactly like what the wizard's Step 1 produces from form inputs.
FORM_DICT = {
    "device_name": "PortaVac NPWT System", "manufacturer": "Acme Medical",
    "device_description": "Portable negative pressure wound therapy system.",
    "intended_purpose": "Promotion of wound healing via controlled negative pressure.",
    "classification": "Class IIb", "classification_rule": "Rule 11",
    "device_synonyms": ["NPWT", "negative pressure wound therapy"],
    "comparator_devices": [],
    "medical_condition": ["chronic wound", "diabetic foot ulcer"],
    "technology_category": ["wound dressing"], "therapeutic_area": ["wound care"],
    "date_from": "2015/01/01", "date_to": "2025/12/31", "languages": ["English"],
    "track1_inclusion_criteria": ["Human clinical study of NPWT"],
    "track1_exclusion_criteria": ["Animal or in vitro studies only"],
    "track2_inclusion_criteria": ["Characterises the standard of care"],
    "track2_exclusion_criteria": ["Not about the relevant condition"],
    "inclusion_criteria": ["Human clinical study of NPWT"],
    "exclusion_criteria": ["Animal or in vitro studies only"],
    "equivalence_claimed": True,
    "equivalent_devices": [{
        "name": "VacuHeal Pro NPWT System", "model": "VH-2000",
        "technical_characteristics": "Same operating principle.",
        "biological_characteristics": "Same contacting materials.",
        "clinical_characteristics": "Same indications and population.",
        "differences_and_justification": "Minor foam pore size difference; not significant.",
        "technical_documentation_access": "Public IFU and literature only.",
    }],
    "manufacturer_claims": [],
    "pico_population": "adults with chronic wounds",
    "pico_intervention": "NPWT", "pico_comparator": "standard dressings",
    "pico_outcomes": "wound healing, adverse events",
    "relevant_gspr": ["GSPR 1", "GSPR 8"],
    "is_legacy_device": True, "is_well_established_technology": True,
    "required_level_of_clinical_evidence": "Literature + PMS, PRRC to confirm.",
    "alternative_treatments_strategy": "Track 2 + guidelines.",
    "pms_data_collection_strategy": "PMS Monitor handoff.",
    "next_evaluation_interval": "24 months",
    "next_evaluation_justification": "WET, stable design, continuous PMS.",
    "evaluator_name": "Dr. A. Example", "evaluator_qualifications": "Wound care specialist",
    "declaration_of_interest_ref": "DOI-2026-001",
}


def main():
    # --- form dict -> valid DeviceProfile ---
    profile = DeviceProfile.from_dict(FORM_DICT)
    assert profile.device_name == "PortaVac NPWT System"
    assert profile.profile_version == "2.2"
    assert profile.equivalent_device_names() == ["VacuHeal Pro NPWT System"]
    assert profile.is_legacy_device and profile.is_well_established_technology
    assert profile.next_evaluation_interval == "24 months"
    # criteria per track resolve
    inc1, exc1 = profile.criteria_for_track("device_specific")
    inc2, exc2 = profile.criteria_for_track("state_of_art")
    assert inc1 and inc2 and inc1 != inc2, "per-track criteria should differ"
    scope_hash = profile.run_scope_hash()
    assert scope_hash

    # --- queries build from the profile (Track 1 includes the equivalent) ---
    queries = pubmed.build_track_queries(profile)
    assert "VacuHeal" in queries["device_specific"]

    # --- state machine through lock (the wizard's Step 3) ---
    tmp = tempfile.mkdtemp()
    db_path = os.path.join(tmp, "wizard.db")
    db.init_db(db_path)
    run_id = "wizard-test-0001"
    db.init_run_state(db_path, run_id, actor="Dr. A. Example")
    assert db.current_state(db_path, run_id) == "draft"
    db.approve_strings(db_path, run_id, queries, actor="Dr. A. Example")
    assert db.current_state(db_path, run_id) == "strings_approved"
    db.lock_run(db_path, run_id, scope_hash, actor="Dr. A. Example")
    assert db.is_locked(db_path, run_id)
    assert db.approved_queries(db_path, run_id) == queries

    # --- get_run_log returns the transition log for the audit trail ---
    db.mark_running(db_path, run_id, actor="system")
    log_rows = db.get_run_log(db_path, run_id)
    assert isinstance(log_rows, list)
    assert any("locked" in (r["message"] or "") for r in log_rows), \
        "state transitions should be logged for the audit trail"

    # --- full six-document set generates end-to-end (CER narrative stubbed) ---
    pc = PrismaCounts(db_records=347, duplicates_removed=12, screened=335,
                      excluded_screening=300, reports_sought=35,
                      reports_not_retrieved=5, assessed=30, excluded_eligibility=8,
                      included=22)
    meta = {"device_specific": {"search_date_utc": "2026-06-15T12:00:00Z",
                                "total_available": 3824, "retrieved": 2000, "capped": True}}
    appraised = [{"pmid": "34763444", "title": "NPWT meta-analysis",
                  "journal": "Ann Palliat Med", "year": "2021", "source": "pubmed",
                  "entry_type": "paper", "appraisal_status": "complete"}]
    records = appraised + [{"pmid": "99999", "title": "Paywalled",
                            "source": "pubmed", "entry_type": "paper",
                            "appraisal_status": "appraisal_incomplete",
                            "track": "device_specific"}]
    state_row = db.get_run_state(db_path, run_id)

    cep = outputs.generate_cep_md(profile, run_id, queries, scope_hash)
    sp = outputs.generate_search_protocol_md(profile, run_id, queries, scope_hash,
                                             ris_sources=["Embase"])
    sr = outputs.generate_search_report_md(profile, run_id, pc, meta, scope_hash=scope_hash)
    tm = outputs.generate_traceability_matrix_md(profile, run_id, records,
                                                 scope_hash=scope_hash)
    audit = outputs.generate_audit_trail_csv(log_rows, state_row)
    cer = outputs.generate_cer_md(profile, run_id, appraised,
                                  [r for r in records if r["pmid"] == "99999"],
                                  pms_signals=[], counts=pc, scope_hash=scope_hash,
                                  narrative_fn=lambda k, c: f"[narrative:{k}]")

    # all six exist, non-trivial, and carry the control block
    for name, doc in [("CEP", cep), ("Protocol", sp), ("Report", sr),
                      ("Matrix", tm), ("CER", cer)]:
        assert len(doc) > 500, f"{name} too short"
        assert "AI-GENERATED FIRST DRAFT" in doc, f"{name} missing disclaimer"
        assert scope_hash in doc, f"{name} missing scope hash"
    assert "timestamp_utc,category,event" in audit
    # the whole set shares one run id
    for doc in (cep, sp, sr, tm, cer):
        assert run_id in doc

    # docx export: every narrative document converts to a valid .docx
    import docx_export
    from docx import Document as _Docx
    for md, title in [(cep, "CEP"), (sp, "Protocol"), (sr, "Report"),
                      (tm, "Matrix"), (cer, "CER")]:
        data = docx_export.md_to_docx_bytes(md, title)
        assert data[:2] == b"PK", f"{title} docx is not a valid zip/docx"
        d = _Docx(io.BytesIO(data))
        assert len(d.paragraphs) > 5, f"{title} docx has too little content"
    print("  docx export: all five narrative docs render to valid .docx OK")

    print("All wizard-logic assertions passed.")
    print("  form dict -> valid DeviceProfile (v2.2, equivalence, legacy) OK")
    print("  queries build with equivalent in Track 1 OK")
    print("  state machine draft -> approved -> locked OK")
    print("  get_run_log returns transition log for audit trail OK")
    print("  full six-document set generates end-to-end, shared run/scope OK")


if __name__ == "__main__":
    main()
