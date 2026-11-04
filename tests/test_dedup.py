"""
Vigil - deduplication tests (multi-pass: PMID / DOI / title).

No network. Verifies the dedup logic collapses the same paper even when it has
different identifiers (the real-CER case once multiple sources/versions exist),
while NOT collapsing genuinely distinct papers.

Run: python tests/test_dedup.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pubmed


def rec(pmid="", doi="", title="", track="device_specific"):
    return {"pmid": pmid, "doi": doi, "title": title, "track": track}


def main():
    # --- Case 1: same PMID across tracks -> collapse to one, tagged 'both' ---
    recs = [
        rec(pmid="111", title="NPWT in diabetic foot ulcers RCT", track="device_specific"),
        rec(pmid="111", title="NPWT in diabetic foot ulcers RCT", track="state_of_art"),
    ]
    unique, dups = pubmed.dedup(recs)
    assert len(unique) == 1 and dups == 1, "same PMID should collapse"
    assert unique[0]["track"] == "both", "cross-track survivor should be tagged both"

    # --- Case 2: same DOI, DIFFERENT PMID (ahead-of-print vs final) -> collapse ---
    recs = [
        rec(pmid="222", doi="10.1000/jwc.2023.45", title="Final version title"),
        rec(pmid="999", doi="10.1000/JWC.2023.45", title="Ahead of print title"),
    ]
    unique, dups = pubmed.dedup(recs)
    assert len(unique) == 1 and dups == 1, "same DOI (diff PMID/case) should collapse"

    # --- Case 3: same normalized title, no DOI on either -> collapse ---
    recs = [
        rec(pmid="333", title="Negative Pressure Wound Therapy: A Review."),
        rec(pmid="444", title="negative pressure wound therapy  a review"),
    ]
    unique, dups = pubmed.dedup(recs)
    assert len(unique) == 1 and dups == 1, "same normalized title should collapse"

    # --- Case 4: genuinely DISTINCT papers -> NOT collapsed ---
    recs = [
        rec(pmid="555", doi="10.1/aaa", title="NPWT for pressure injuries trial"),
        rec(pmid="666", doi="10.2/bbb", title="NPWT for venous leg ulcers cohort study"),
        rec(pmid="777", doi="10.3/ccc", title="Wound dressing comparison study"),
    ]
    unique, dups = pubmed.dedup(recs)
    assert len(unique) == 3 and dups == 0, "distinct papers must not collapse"

    # --- Case 5: short/generic titles with no PMID/DOI must NOT collapse ---
    # (titles under the length threshold are not used as a dedup key)
    recs = [
        rec(title="NPWT"),
        rec(title="NPWT"),
    ]
    unique, dups = pubmed.dedup(recs)
    assert len(unique) == 2 and dups == 0, "short titles must not be a dedup key"

    # --- Case 6: DOI normalization strips URL/prefix forms ---
    assert pubmed._norm_doi("https://doi.org/10.1/AbC") == "10.1/abc"
    assert pubmed._norm_doi("doi:10.1/AbC") == "10.1/abc"
    assert pubmed._norm_doi("") == ""

    print("All dedup assertions passed.")
    print("  same PMID across tracks -> one, tagged 'both' OK")
    print("  same DOI / different PMID (ahead-of-print) -> collapsed OK")
    print("  same normalized title, no DOI -> collapsed OK")
    print("  distinct papers -> not collapsed OK")
    print("  short/generic titles -> not a dedup key OK")
    print("  DOI normalization OK")


if __name__ == "__main__":
    main()
