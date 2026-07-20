"""
Offline end-to-end smoke test for the Vigil CER pipeline (auto-retrieval + 2-phase).

No network, no API keys. Injects:
  - canned PubMed records (NPWT abstracts)
  - fake LLM (screen / abstract-extract / full-text appraise via PDF and via text)
  - fake OA retrieval: PMID ...001 found in PMC (text); ...002 has NO OA -> manual

Covers:
  Phase A: search -> screen -> abstract pass -> AUTO-RETRIEVE (PMC hit) ->
           auto full-text appraisal -> ...001 fully appraised, ...002 -> manual list.
  Phase B: PRRC uploads PDF for ...002 -> appraised -> both included.

Run:  python tests/offline_demo.py
"""
import os, sys, json
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pubmed, screen, extract, retrieve, appraise, pipeline, db
from device_profile import DeviceProfile

CANNED = [
    {"pmid": "30000001", "track": "device_specific",
     "title": "Negative pressure wound therapy for diabetic foot ulcers: an RCT",
     "abstract": "RCT of NPWT vs standard dressing in 120 diabetic foot ulcers.",
     "journal": "J Wound Care", "year": "2019", "doi": "10.1000/jwc.2019.001"},
    {"pmid": "30000002", "track": "device_specific",
     "title": "Portable NPWT in surgical wound dehiscence: prospective cohort",
     "abstract": "Cohort of 64 dehisced surgical wounds treated with portable NPWT.",
     "journal": "Int Wound J", "year": "2021", "doi": "10.1000/iwj.2021.002"},
    {"pmid": "30000004", "track": "device_specific",
     "title": "NPWT in pressure ulcers: a randomised study",
     "abstract": "Randomised study of NPWT in 90 pressure ulcer patients.",
     "journal": "Wound Repair", "year": "2020", "doi": "10.1000/wr.2020.004"},
    {"pmid": "30000003", "track": "state_of_art",
     "title": "State of the art in chronic wound management: a review",
     "abstract": "Review of chronic wound management. No device-specific data.",
     "journal": "Adv Wound Care", "year": "2022", "doi": "10.1000/awc.2022.003"},
]

def fake_run_track(query, track_name, retmax):
    return [dict(r) for r in CANNED if r["track"] == track_name]

def _pmid(u):
    for p in ("30000001","30000002","30000003","30000004"):
        if p in u: return p
    return "0"

def fake_call_json(model, system, user_stable, user_variable, max_tokens):
    user = user_stable + user_variable
    if "verdict" in user:
        p = _pmid(user)
        if p == "30000003":
            return {"pmid": p, "verdict": "exclude", "matched_inclusion": [],
                    "matched_exclusion": ["Review"], "rationale": "Review, no device data."}
        return {"pmid": p, "verdict": "include", "matched_inclusion": ["Clinical study"],
                "matched_exclusion": [], "rationale": "NPWT clinical study."}
    p = _pmid(user)
    return {"pmid": p, "study_design": "abstract-level",
            "population": {"n": None, "indication": "wound", "description": None},
            "intervention": "NPWT", "comparator": None, "performance_outcomes": [],
            "adverse_events": [], "not_reported": ["most"], "requires_fulltext": ["all"]}

def _appraisal(p, where):
    return {"pmid": p, "appraisal_mode": "fulltext", "study_design": "RCT",
            "population": {"n": 120, "indication": "diabetic foot ulcer",
                           "setting": "outpatient", "description": "randomised"},
            "intervention": "NPWT", "comparator": "standard dressing", "follow_up": "16 weeks",
            "appraisal": {"methodological_quality": "Low risk of bias.",
                          "relevance_to_device": "device-specific",
                          "data_contribution": "pivotal",
                          "contribution_rationale": "Direct RCT.",
                          "limitations": ["single centre"], "risk_of_bias_notes": "ok"},
            "performance_outcomes": [{"outcome": "complete healing", "value": "78% vs 56%",
                "timepoint": "16 weeks", "p_value": "0.01",
                "source_location": f"Table 2 ({where})", "source_pmid": p}],
            "adverse_events": [{"event": "wound infection", "count": 6, "rate": "5%",
                "severity": "moderate", "device_related": "unclear",
                "source_location": "Table 3", "source_pmid": p}],
            "not_reported": []}

def fake_appraise_pdf(model, system, user_stable, user_variable, pdf_bytes, max_tokens):
    assert pdf_bytes[:5] == b"%PDF-"
    return _appraisal(_pmid(user_stable + user_variable), "PDF")

def fake_appraise_text(model, system, user_stable, user_variable, fulltext, max_tokens):
    assert "FULL TEXT" in fulltext or len(fulltext) > 10
    return _appraisal(_pmid(user_stable + user_variable), "PMC text")

def _make_pdf(lines):
    from reportlab.pdfgen import canvas
    from reportlab.lib.pagesizes import letter
    import io as _io
    buf = _io.BytesIO(); c = canvas.Canvas(buf, pagesize=letter); y = 750
    for ln in lines:
        c.drawString(72, y, ln); y -= 18
    c.showPage(); c.save(); return buf.getvalue()


def fake_retrieve_batch(records, progress=lambda s: None):
    # 001 -> PMC (correct identity, verifies via DOI)
    # 002 -> no OA copy (manual)
    # 004 -> Unpaywall returns the WRONG paper's PDF (must FAIL verification)
    wrong_pdf = _make_pdf([
        "Hyperbaric oxygen for venous leg ulcers: a meta-analysis",
        "Some Other Journal 2018. doi:10.1000/wrong.2018.999",
        "Abstract: pooled analysis of 14 trials ...",
    ])
    out = {}
    for r in records:
        if r["pmid"] == "30000001":
            out[r["pmid"]] = {"status": "pmc_xml", "kind": "xml_text",
                "text": "FULL TEXT of the NPWT RCT ... Table 2 ... Table 3 ...",
                "pdf_bytes": None,
                "found_doi": "10.1000/jwc.2019.001",  # matches record -> verifies
                "found_title": r["title"],
                "source_url": "https://pmc/PMC123/"}
        elif r["pmid"] == "30000004":
            out[r["pmid"]] = {"status": "unpaywall_pdf", "kind": "pdf",
                "text": None, "pdf_bytes": wrong_pdf,
                "source_url": "https://repo.example/wrong.pdf"}
        else:  # 002 -> no OA
            out[r["pmid"]] = {"status": "paywalled_manual", "kind": None,
                "text": None, "pdf_bytes": None, "source_url": None}
        progress(f"  retrieve {r['pmid']}: {out[r['pmid']]['status']}")
    return out

def fake_call_text(model, system, user_stable, user_variable, max_tokens):
    return ("## 1. Summary\nTwo device-specific studies appraised.\n\n"
            "## 2. Device-specific clinical evidence (Track 1)\n"
            "Healing 78% vs 56% (PMID 30000001, Table 2). Infection 6 (PMID 30000001, Table 3).\n\n"
            "## 3. State of the art (Track 2)\nSee report.\n\n"
            "## 4. Papers flagged appraisal incomplete\n[none]\n\n"
            "## 5. Post-market signals\n[none]\n\n"
            "## 6. Human-only sections\n"
            "[PRRC TO COMPLETE: Demonstration of equivalence - MEDDEV Appendix A1.]\n")

def main():
    pubmed.run_track = fake_run_track
    screen.call_json = fake_call_json
    extract.call_json = fake_call_json
    retrieve.retrieve_batch = fake_retrieve_batch
    # appraise uses pdf_call/text_call params -> inject via pipeline by patching defaults
    appraise.call_json_pdf = fake_appraise_pdf
    appraise.call_json_fulltext_text = fake_appraise_text
    import llm; llm.call_text = fake_call_text

    prof = DeviceProfile.from_json(
        os.path.join(os.path.dirname(__file__), "..", "devices", "npwt_sample.json"))
    db_path = "/tmp/vigil_test.db"
    if os.path.exists(db_path): os.remove(db_path)

    print("PHASE A (search + screen + retrieve + VERIFY + auto-appraise)")
    a = pipeline.run_search_and_screen(prof, db_path=db_path, retmax=10,
                                       progress=lambda s: print("  *", s))
    # 001 -> PMC, identity verified, auto-appraised.
    # 002 -> no OA (manual). 004 -> Unpaywall returned WRONG paper, verification
    #         FAILED, so it is NOT appraised and is routed to manual.
    assert a["counts"]["included"] == 1, a["counts"]
    manual_pmids = sorted(r["pmid"] for r in a["manual_upload_list"])
    assert manual_pmids == ["30000002", "30000004"], manual_pmids
    # Confirm 004 was rejected specifically by verification, not no-OA.
    rec004 = db.get_records(db_path, a["run_id"], "pmid='30000004'")[0]
    assert rec004["retrieval_source"] == "auto_unverified", rec004["retrieval_source"]
    assert rec004["verification_result"] == "mismatch", rec004["verification_result"]
    print(f"  auto-appraised: {a['counts']['included']} | manual: {manual_pmids}")
    print(f"  PMID 30000004 verification: {rec004['verification_result']} "
          f"(score {rec004['verification_score']}) -> blocked from appraisal OK")

    print("PHASE B (PRRC uploads the two residual papers - with CORRECT PDFs)")
    pdf_002 = _make_pdf(["Portable NPWT in surgical wound dehiscence: prospective cohort",
                         "Int Wound J 2021. doi:10.1000/iwj.2021.002"])
    pdf_004 = _make_pdf(["NPWT in pressure ulcers: a randomised study",
                         "Wound Repair 2020. doi:10.1000/wr.2020.004"])
    b = pipeline.run_fulltext_appraisal(
        prof, a["run_id"], {"30000002": pdf_002, "30000004": pdf_004},
        db_path=db_path, duplicates=a["_duplicates"], queries=a["queries"],
        progress=lambda s: print("  *", s))
    assert b["counts"]["included"] == 3, b["counts"]
    assert len(b["manual_upload_list"]) == 0, b["manual_upload_list"]
    assert "PMC OA" in b["search_report"], "report should record PMC as a source"

    for name, key in [("vigil_search_report.md","search_report"),
                      ("vigil_prisma.svg","prisma_svg")]:
        with open(f"/tmp/{name}","w") as f: f.write(b[key])

    # CER Word-doc narrative is generated on demand (app.py step 6), not by
    # the pipeline - exercise that path here with the same fakes.
    import outputs
    import draft as draft_mod
    records = db.retrieval_list(db_path, a["run_id"])
    appraised = [r for r in records if r.get("appraisal_status") == "complete"]
    incomplete = [r for r in records if r.get("appraisal_status") == "appraisal_incomplete"]
    cer = outputs.generate_cer_md(prof, a["run_id"], appraised, incomplete,
                                  counts=b["counts"], scope_hash=prof.run_scope_hash(),
                                  narrative_fn=draft_mod.make_narrative_fn(call=fake_call_text))
    assert "Not generated in this offline render" not in cer, \
        "narrative_fn should produce real (fake-LLM) prose, not the placeholder"
    with open("/tmp/vigil_cer_draft.md","w") as f: f.write(cer)

    print("\nFinal PRISMA counts:", json.dumps(b["counts"]))
    print("All assertions passed. Auto-retrieval + verification gate + manual fallback verified.")

if __name__ == "__main__":
    main()
