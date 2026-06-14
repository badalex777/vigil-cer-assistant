"""
Vigil - RIS ingestor tests (offline).

No network. Verifies the RIS parser handles real-world export quirks and that
ingested references flow through the same dedup as PubMed/CT.gov - in particular
that the SAME study found in PubMed AND in an Embase export collapses to one (the
whole point of multi-source dedup).

Run: python tests/test_ris.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import ris_ingest
import pubmed


STANDARD_RIS = """TY  - JOUR
TI  - Negative pressure wound therapy for diabetic foot ulcers
AB  - A randomised controlled trial comparing NPWT to standard dressings.
JO  - Journal of Wound Care
PY  - 2022
DO  - 10.12968/jowc.2022.31.4.300
AU  - Smith J
AU  - Garcia M
ER  -

TY  - JOUR
T1  - Pressure ulcer management with NPWT: a cohort study
N2  - This cohort followed 80 patients over 12 weeks
      with stage 3 and 4 pressure injuries.
JF  - International Wound Journal
Y1  - 2021
DO  - 10.1111/iwj.13500
AU  - Lee K
ER  -
"""

# A reference with no title - must be skipped, not crash.
NO_TITLE_RIS = """TY  - JOUR
AB  - Some abstract with no title field at all.
PY  - 2020
ER  -
"""


def main():
    # --- standard parse: two refs, fields mapped ---
    recs, meta = ris_ingest.parse_ris(STANDARD_RIS, source="embase_export")
    assert len(recs) == 2, f"expected 2 refs, got {len(recs)}"
    assert meta["parsed"] == 2 and meta["references_in_file"] == 2

    r0 = recs[0]
    assert r0["title"].startswith("Negative pressure wound therapy")
    assert r0["doi"] == "10.12968/jowc.2022.31.4.300"
    assert r0["journal"] == "Journal of Wound Care"
    assert r0["year"] == "2022"
    assert r0["source"] == "embase_export"
    assert r0["entry_type"] == "paper"
    assert r0["authors"] == ["Smith J", "Garcia M"]
    assert r0["external_id"].startswith("doi:"), "id should derive from DOI"

    # --- dialect variants: T1 (title), N2 (abstract), JF (journal), Y1 (year) ---
    r1 = recs[1]
    assert r1["title"].startswith("Pressure ulcer management"), "T1 tag not parsed"
    assert "80 patients" in r1["abstract"], "N2 abstract not parsed"
    assert "12 weeks" in r1["abstract"], "continuation line not appended"
    assert r1["journal"] == "International Wound Journal", "JF tag not parsed"
    assert r1["year"] == "2021", "Y1 tag not parsed"

    # --- untitled reference is skipped, not crashing ---
    recs2, meta2 = ris_ingest.parse_ris(NO_TITLE_RIS, source="cochrane_export")
    assert len(recs2) == 0 and meta2["skipped_no_title"] == 1

    # --- empty / junk input degrades gracefully ---
    recs3, _ = ris_ingest.parse_ris("", source="x")
    assert recs3 == []
    recs4, _ = ris_ingest.parse_ris("not a ris file at all\njust text\n", source="x")
    assert recs4 == [], "non-RIS text should parse to zero refs, not crash"

    # --- CROSS-SOURCE DEDUP: same DOI in PubMed and in the Embase export -> one ---
    pubmed_copy = {
        "pmid": "34763444",
        "doi": "10.12968/JOWC.2022.31.4.300",   # same DOI, different case
        "title": "Negative pressure wound therapy for diabetic foot ulcers",
        "track": "device_specific", "entry_type": "paper",
    }
    merged = [pubmed_copy] + recs  # pubmed copy + the 2 embase refs
    unique, dups = pubmed.dedup(merged)
    # the embase ref with the same DOI collapses into the pubmed copy; the other
    # embase ref (different DOI) stays -> 2 unique, 1 duplicate removed
    assert len(unique) == 2 and dups == 1, (
        f"cross-source DOI dedup failed: {len(unique)} unique, {dups} dups")

    # --- two copies of the same Embase export ref -> collapse by external_id ---
    u2, d2 = pubmed.dedup([dict(recs[0]), dict(recs[0])])
    assert len(u2) == 1 and d2 == 1, "same external_id should collapse"

    print("All RIS ingestor assertions passed.")
    print("  standard RIS: 2 refs, fields mapped OK")
    print("  dialect variants (T1/N2/JF/Y1) + continuation line OK")
    print("  untitled reference skipped OK")
    print("  empty/junk input degrades gracefully OK")
    print("  CROSS-SOURCE dedup: same DOI in PubMed + Embase -> one OK")
    print("  duplicate export ref collapses by external_id OK")


if __name__ == "__main__":
    main()
