"""
Unit test for verify.py — runs on REAL PDF bytes (generated with reportlab),
not mocks. Proves the deterministic identity gate actually works.

Run:  python tests/test_verify.py
"""
import os
import sys
import io

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import verify


def make_pdf(lines: list[str]) -> bytes:
    from reportlab.pdfgen import canvas
    from reportlab.lib.pagesizes import letter
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=letter)
    y = 750
    for ln in lines:
        c.drawString(72, y, ln)
        y -= 18
    c.showPage()
    c.save()
    return buf.getvalue()


REC_A = {"pmid": "30000001", "doi": "10.1000/jwc.2019.001",
         "title": "Negative pressure wound therapy for diabetic foot ulcers: an RCT"}
REC_B = {"pmid": "30000099", "doi": "10.1000/other.2020.555",
         "title": "Hyperbaric oxygen therapy for venous leg ulcers: a meta-analysis"}


def test_doi_match_passes():
    pdf = make_pdf([
        "Negative pressure wound therapy for diabetic foot ulcers: an RCT",
        "Journal of Wound Care, 2019.  doi:10.1000/jwc.2019.001",
        "Abstract: We randomised 120 patients ...",
    ])
    v = verify.verdict_for(REC_A, {"kind": "pdf", "pdf_bytes": pdf})
    assert v["result"] == "verified_doi", v
    print("  ✓ correct paper, DOI printed -> verified_doi")


def test_wrong_paper_rejected():
    # PDF is actually paper B; we expected paper A.
    pdf = make_pdf([
        "Hyperbaric oxygen therapy for venous leg ulcers: a meta-analysis",
        "Some Other Journal, 2020.  doi:10.1000/other.2020.555",
        "Abstract: We pooled 14 trials ...",
    ])
    v = verify.verdict_for(REC_A, {"kind": "pdf", "pdf_bytes": pdf})
    assert v["result"] == "mismatch", v
    print(f"  ✓ wrong paper rejected -> mismatch (score {v['score']})")


def test_title_fallback_no_doi():
    # No DOI printed; title present -> title fallback should verify.
    pdf = make_pdf([
        "Negative pressure wound therapy for diabetic foot ulcers: an RCT",
        "Journal of Wound Care, 2019.",
        "Abstract: We randomised 120 patients with diabetic foot ulcers ...",
    ])
    v = verify.verdict_for(REC_A, {"kind": "pdf", "pdf_bytes": pdf})
    assert v["result"] in ("verified_title", "verified_doi"), v
    print(f"  ✓ no DOI, title present -> {v['result']} (score {v['score']})")


def test_unverifiable_empty():
    pdf = make_pdf([" "])  # essentially no extractable identifiers
    v = verify.verdict_for(REC_A, {"kind": "pdf", "pdf_bytes": pdf})
    assert v["result"] == "unverifiable", v
    print(f"  ✓ no identifiers -> {v['result']}")


def test_pmc_structured():
    # PMC path supplies structured DOI + title from JATS article-meta.
    good = verify.verdict_for(REC_A, {
        "kind": "xml_text", "found_doi": "10.1000/jwc.2019.001",
        "found_title": REC_A["title"], "text": "full text body ..."})
    assert good["result"] == "verified_doi", good
    bad = verify.verdict_for(REC_A, {
        "kind": "xml_text", "found_doi": "10.1000/other.2020.555",
        "found_title": REC_B["title"], "text": "full text body ..."})
    assert bad["result"] == "mismatch", bad
    print("  ✓ PMC structured ids: right->verified_doi, wrong->mismatch")


def main():
    print("VERIFY UNIT TESTS (real PDFs)")
    test_doi_match_passes()
    test_wrong_paper_rejected()
    test_title_fallback_no_doi()
    test_unverifiable_empty()
    test_pmc_structured()
    print("All verify.py assertions passed.")


if __name__ == "__main__":
    main()
