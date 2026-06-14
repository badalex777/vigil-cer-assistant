"""
Vigil - ClinicalTrials.gov client tests (offline, mocked).

No network. Mocks clinicaltrials._ctgov_get to return synthetic API v2 JSON and
verifies:
  - trial registrations are mapped into the internal record format,
  - they are tagged source='clinicaltrials_gov', entry_type='trial_registration',
  - the synthesized abstract carries the registration marker the screener keys on,
  - nextPageToken pagination retrieves across pages and respects the cap,
  - dedup keeps a trial registration separate from a published paper with the same
    title (different evidence types must both be counted), but collapses two copies
    of the same NCT id.

Run: python tests/test_ctgov.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import clinicaltrials
import pubmed


def _fake_study(nct, title, status="COMPLETED", has_results=False):
    return {
        "protocolSection": {
            "identificationModule": {"nctId": nct, "briefTitle": title},
            "statusModule": {"overallStatus": status,
                             "startDateStruct": {"date": "2021-03-01"}},
            "descriptionModule": {"briefSummary": f"Summary of {title}."},
            "designModule": {"studyType": "INTERVENTIONAL",
                             "phases": ["PHASE3"],
                             "enrollmentInfo": {"count": 120}},
            "conditionsModule": {"conditions": ["Diabetic Foot Ulcer"]},
        },
        "hasResults": has_results,
    }


def _make_profile():
    from device_profile import DeviceProfile
    return DeviceProfile.from_json("devices/npwt_sample.json")


def main():
    profile = _make_profile()

    # --- query builder uses CT.gov syntax, not PubMed [tiab] ---
    q = clinicaltrials.build_ctgov_query(profile)
    assert "query.cond" in q["params"], "should build a condition query"
    assert "query.intr" in q["params"], "should build an intervention query"
    assert "[tiab]" not in q["human"], "must NOT use PubMed syntax"

    # --- mock the API: 3 studies across 2 pages ---
    pages = [
        {"totalCount": 3, "nextPageToken": "TOK2",
         "studies": [_fake_study("NCT001", "NPWT for diabetic foot ulcer trial A"),
                     _fake_study("NCT002", "NPWT for pressure ulcer trial B")]},
        {"totalCount": 3,
         "studies": [_fake_study("NCT003", "NPWT wound healing trial C",
                                 has_results=True)]},
    ]
    calls = {"n": 0}

    def fake_get(params):
        i = calls["n"]
        calls["n"] += 1
        return pages[i] if i < len(pages) else {"studies": []}

    orig = clinicaltrials._ctgov_get
    clinicaltrials._ctgov_get = fake_get
    try:
        records, meta = clinicaltrials.run_ctgov(profile, track_name="device_specific")
    finally:
        clinicaltrials._ctgov_get = orig

    assert len(records) == 3, f"expected 3 registrations, got {len(records)}"
    assert meta["total_available"] == 3
    assert meta["source"] == "clinicaltrials_gov"
    assert meta["search_date_utc"].endswith("Z")
    # every record is a tagged trial registration
    for r in records:
        assert r["source"] == "clinicaltrials_gov"
        assert r["entry_type"] == "trial_registration"
        assert r["registry_id"].startswith("NCT")
        assert r["abstract"].startswith("[CLINICAL TRIAL REGISTRATION"), \
            "abstract must carry the marker the screener keys on"
        assert r["track"] == "device_specific"
    # results-posted flag mapped
    assert records[2]["has_results"] is True

    # --- cap respected ---
    calls["n"] = 0
    clinicaltrials._ctgov_get = fake_get
    try:
        capped_recs, capped_meta = clinicaltrials.run_ctgov(
            profile, max_hits=2)
    finally:
        clinicaltrials._ctgov_get = orig
    assert len(capped_recs) == 2 and capped_meta["capped"] is True, "cap not respected"

    # --- dedup: trial registration vs same-title paper -> BOTH kept ---
    paper = {"pmid": "123", "doi": "10.1/x",
             "title": "NPWT for diabetic foot ulcer trial A",
             "track": "device_specific", "entry_type": "paper"}
    trial = dict(records[0])  # same title, but a trial registration
    unique, dups = pubmed.dedup([paper, trial])
    assert len(unique) == 2 and dups == 0, \
        "a trial registration and a same-title paper are different evidence; keep both"

    # --- dedup: two copies of the same NCT -> collapse to one ---
    unique2, dups2 = pubmed.dedup([dict(records[0]), dict(records[0])])
    assert len(unique2) == 1 and dups2 == 1, "same NCT id should collapse"

    print("All ClinicalTrials.gov assertions passed.")
    print("  CT.gov query uses registry syntax (not PubMed) OK")
    print("  3 registrations mapped across 2 pages (nextPageToken) OK")
    print("  records tagged trial_registration + registration marker OK")
    print("  cap respected OK")
    print("  dedup keeps trial vs same-title paper separate OK")
    print("  dedup collapses duplicate NCT OK")


if __name__ == "__main__":
    main()
