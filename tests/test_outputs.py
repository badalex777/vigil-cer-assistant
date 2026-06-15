"""
Vigil - output set tests (Block 4): control block + CEP.

No network, no AI. Verifies the shared foundation and the first document (CEP):
  - the control block carries run_id, scope_hash, profile_version, evaluator,
  - the mandatory AI-draft disclaimer is present,
  - the CEP renders from the profile ALONE (no search results needed - the
    "downloadable at lock" property),
  - legacy-device elements (MDCG 2020-6) appear when is_legacy_device,
  - PRRC judgement placeholders are present and clearly marked,
  - no Python list-repr leaks into the regulatory text.

Run: python tests/test_outputs.py
"""
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import outputs
from device_profile import DeviceProfile

DEVICE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                      "devices", "npwt_sample.json")


def main():
    profile = DeviceProfile.from_json(DEVICE)
    run_id = "PortaVac-test1234"

    # --- control block ---
    cb = outputs.build_control_block(profile, run_id, "Test Document")
    assert cb["run_id"] == run_id
    assert cb["scope_hash"], "scope hash must be present"
    assert cb["profile_version"] == "2.2"
    assert cb["device_name"] == profile.device_name

    hdr = outputs.render_control_block_md(cb)
    assert "AI-GENERATED FIRST DRAFT" in hdr, "mandatory disclaimer missing"
    assert run_id in hdr
    assert cb["scope_hash"] in hdr

    # --- CEP renders from the profile ALONE (no approved_queries passed) ---
    cep_no_q = outputs.generate_cep_md(profile, run_id)
    assert "Clinical Evaluation Plan" in cep_no_q
    assert "AI-GENERATED FIRST DRAFT" in cep_no_q, "CEP missing disclaimer"
    # the four MDR Annex XIV 1a anchors
    for anchor in ["intended purpose", "GSPR", "benefit-risk", "PICO"]:
        assert anchor.lower() in cep_no_q.lower(), f"CEP missing anchor: {anchor}"

    # --- legacy-device elements appear (this fixture is a legacy WET device) ---
    assert profile.is_legacy_device, "fixture should be a legacy device"
    assert "MDCG 2020-6" in cep_no_q, "legacy CEP must cite MDCG 2020-6"
    assert "Well-established technology" in cep_no_q
    assert "PMS data collection strategy" in cep_no_q
    assert "level of clinical evidence" in cep_no_q.lower()

    # --- PRRC judgement placeholders present and clearly marked ---
    placeholders = cep_no_q.count("[PRRC JUDGEMENT REQUIRED")
    assert placeholders >= 2, f"expected PRRC placeholders, found {placeholders}"
    # benefit-risk acceptability and the clinical-investigation/PMCF decision are
    # judgements the system must NOT make
    assert "Benefit-risk acceptability" in cep_no_q
    assert "clinical investigation" in cep_no_q.lower()

    # --- CEP with approved queries renders them verbatim ---
    queries = {
        "device_specific": '("NPWT"[tiab] OR "VacuHeal"[tiab]) AND English[lang]',
        "state_of_art": '("chronic wound"[tiab]) AND English[lang]',
    }
    cep_q = outputs.generate_cep_md(profile, run_id, approved_queries=queries)
    assert '("NPWT"[tiab] OR "VacuHeal"[tiab])' in cep_q, "approved strings not rendered"

    # --- no Python list-repr leaks anywhere in the document ---
    for doc in (cep_no_q, cep_q):
        leaks = re.findall(r"\['.*?'\]", doc)
        assert not leaks, f"list-repr leaked into document: {leaks}"

    # --- state-of-the-art correctly framed as NOT clinical data ---
    assert "does NOT constitute clinical data" in cep_no_q \
        or "not constitute clinical data" in cep_no_q.lower(), \
        "Track 2 must be framed as context, not clinical data"

    # --- Document 2: Search Protocol (A5.3 elements) ---
    sp = outputs.generate_search_protocol_md(profile, run_id, queries,
                                             ris_sources=["Embase export"])
    assert "AI-GENERATED FIRST DRAFT" in sp
    for elem in ["Sources and justification", "Search strings", "Selection criteria",
                 "Deduplication strategy", "appraisal plan".title()[:8],
                 "analysis plan"]:
        assert elem.lower() in sp.lower(), f"Search Protocol missing A5.3 element: {elem}"
    assert '("NPWT"[tiab] OR "VacuHeal"[tiab])' in sp, "protocol must render approved strings verbatim"
    assert "Embase export" in sp, "PRRC-declared source should appear"
    assert "LOCKED" in sp, "criteria-locked statement required"

    # --- Document 3: Search Report (PRISMA + per-source + deviations) ---
    import prisma
    counts = prisma.PrismaCounts(db_records=347, duplicates_removed=12, screened=335,
                                 excluded_screening=300, reports_sought=35,
                                 reports_not_retrieved=5, assessed=30,
                                 excluded_eligibility=8, included=22)
    meta = {
        "device_specific": {"search_date_utc": "2026-06-14T18:00:00Z",
                            "total_available": 3824, "retrieved": 2000, "capped": True},
        "clinicaltrials_gov": {"search_date_utc": "2026-06-14T18:01:00Z",
                               "total_available": 650, "retrieved": 650, "capped": False},
    }
    sr = outputs.generate_search_report_md(profile, run_id, counts, meta)
    assert "AI-GENERATED FIRST DRAFT" in sr
    assert "PRISMA 2020 flow" in sr
    assert "Included in clinical evaluation: 22" in sr, "final included count must show"
    assert "2026-06-14T18:00:00Z" in sr, "per-source search date must appear"
    assert "Deviations from the search protocol" in sr, "deviations placeholder required"
    assert "Duplicates removed: 12" in sr

    # --- Document 5: Traceability Matrix ---
    recs = [
        {"pmid": "123", "source": "pubmed", "entry_type": "paper",
         "track": "device_specific", "screen_verdict": "include"},
        {"registry_id": "NCT001", "source": "clinicaltrials_gov",
         "entry_type": "trial_registration", "track": "device_specific",
         "screen_verdict": "include"},
        {"external_id": "doi:10.1/x", "source": "embase_export", "entry_type": "paper",
         "track": "state_of_art", "screen_verdict": "uncertain"},
    ]
    tm = outputs.generate_traceability_matrix_md(profile, run_id, recs)
    assert "AI-GENERATED FIRST DRAFT" in tm
    assert "NCT001" in tm and "Trial Registration" in tm
    assert "embase_export" in tm, "RIS source should be traceable"
    assert "Total retained records: 3" in tm

    # --- Document 6: Audit Trail CSV ---
    logs = [{"ts": 1718000000, "stage": "search", "message": "t1=10 t2=10"},
            {"ts": 1718000100, "stage": "screen", "message": "22 included"}]
    state = {"created_at": 1717990000, "approved_at": 1717995000,
             "locked_at": 1717999000, "locked_scope_hash": "abc123",
             "actor": "prrc@client", "running_at": 1718000000}
    csv_text = outputs.generate_audit_trail_csv(logs, state)
    assert "timestamp_utc,category,event" in csv_text, "CSV header required"
    assert "state_transition" in csv_text, "state transitions must be logged"
    assert "scope_hash=abc123" in csv_text, "lock must record scope_hash"
    assert "-> locked" in csv_text

    # --- Document 4: CER first draft (mocked narrative, no Opus cost) ---
    def stub_narrative(section_key, context):
        return f"[STUB NARRATIVE: {section_key}]"

    appraised = [
        {"pmid": "34763444", "title": "NPWT meta-analysis for diabetic foot ulcers",
         "journal": "Ann Palliat Med", "year": "2021", "source": "pubmed",
         "entry_type": "paper", "extraction_json": '{"outcome":"healing improved"}'},
        {"pmid": "37777272", "title": "NPWT vs alginate RCT", "journal": "Saudi Med J",
         "year": "2023", "source": "pubmed", "entry_type": "paper"},
    ]
    incomplete = [{"pmid": "99999", "title": "Paywalled NPWT study"}]
    pms = [{"signal_id": "SIG-001", "summary": "Dressing-seal failures in home care"}]

    cer = outputs.generate_cer_md(profile, run_id, appraised, incomplete, pms,
                                  narrative_fn=stub_narrative)
    assert "AI-GENERATED FIRST DRAFT" in cer
    # A9 structure: the major sections must be present
    for sec in ["1. Summary", "2. Scope", "3. Clinical background", "4. Device under",
                "5. Summary of the clinical data", "6. Analysis", "7. PMCF",
                "8. Conclusions", "9. Date of next evaluation",
                "10. Dates and signatures", "11. References"]:
        assert sec in cer, f"CER missing A9 section: {sec}"

    # Greenlight refinement 1: evaluator must require relevant clinical specialty
    assert "clinical specialty relevant to the device" in cer, \
        "evaluator placeholder must require relevant clinical specialty"
    # Greenlight refinement 2: date-of-next-evaluation now populated from the profile
    # (PRRC defines the interval up front, it flows into the CER)
    assert "Update frequency (defined by the PRRC)" in cer, \
        "next-evaluation interval should populate from the profile"
    assert "24 months" in cer, "PRRC-defined interval should render"
    assert "well-established technology" in cer.lower()

    # equivalence ASSEMBLED, never judged
    assert "VacuHeal" in cer, "equivalence table must name the equivalent device"
    assert "| Technical |" in cer and "| Biological |" in cer and "| Clinical |" in cer, \
        "3-characteristic comparison table required"
    assert "Vigil does not judge whether equivalence holds" in cer
    assert "Equivalence determination" in cer, "equivalence must end in a PRRC placeholder"

    # every judgement is a PRRC placeholder; conclusions are NEVER written by AI
    n_ph = cer.count("[PRRC JUDGEMENT REQUIRED")
    assert n_ph >= 6, f"expected >=6 PRRC judgement placeholders, found {n_ph}"
    assert "Vigil does NOT write conclusions" in cer, "conclusions must be a placeholder"
    for judgement in ["Benefit-risk acceptability", "Residual-risk acceptability",
                      "Conformity with the relevant GSPRs",
                      "Conclusions of the clinical evaluation"]:
        assert judgement in cer, f"missing judgement placeholder: {judgement}"

    # legacy device -> sufficiency-of-evidence section (MDCG 2020-6)
    assert "Sufficiency of clinical evidence" in cer, "legacy sufficiency section required"
    assert "MDCG 2020-6" in cer
    assert "Reliance solely on complaints and vigilance is not sufficient" in cer

    # narrative confined to descriptive sections; judgement sections have no AI prose
    assert "[STUB NARRATIVE: state_of_art]" in cer, "descriptive sections get AI prose"
    assert "[STUB NARRATIVE: evidence_summary]" in cer

    # references assembled from appraised records; incomplete record NOT a reference
    assert "[34763444]" in cer and "[37777272]" in cer
    assert "99999" not in cer.split("## 11. References")[-1], \
        "appraisal-incomplete record must not appear as an appraised reference"

    # PMS signal surfaced for triage (not concluded on)
    assert "SIG-001" in cer

    # default (no narrative_fn) renders a clear deterministic placeholder, no crash
    cer_offline = outputs.generate_cer_md(profile, run_id, appraised)
    assert "Not generated in this offline render" in cer_offline

    print("All output-set (control block + CEP) assertions passed.")
    print("  control block: run_id + scope_hash + profile_version + disclaimer OK")
    print("  CEP renders from profile alone (downloadable at lock) OK")
    print("  MDR Annex XIV 1a anchors present OK")
    print("  legacy-device elements (MDCG 2020-6) present OK")
    print("  PRRC judgement placeholders present and marked OK")
    print("  approved search strings rendered verbatim OK")
    print("  no list-repr leaks; state-of-art framed as non-clinical-data OK")
    print("  Search Protocol: A5.3 elements + locked criteria OK")
    print("  Search Report: PRISMA + per-source dates + deviations OK")
    print("  Traceability Matrix: source-typed rows OK")
    print("  Audit Trail CSV: state transitions + scope_hash OK")
    print("  CER: full A9 structure OK")
    print("  CER: equivalence ASSEMBLED not judged (ends in PRRC placeholder) OK")
    print("  CER: all judgements are PRRC placeholders; conclusions never AI-written OK")
    print("  CER: legacy sufficiency section + references + PMS handoff OK")


if __name__ == "__main__":
    main()
