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
    assert cb["profile_version"] == "2.1"
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

    print("All output-set (control block + CEP) assertions passed.")
    print("  control block: run_id + scope_hash + profile_version + disclaimer OK")
    print("  CEP renders from profile alone (downloadable at lock) OK")
    print("  MDR Annex XIV 1a anchors present OK")
    print("  legacy-device elements (MDCG 2020-6) present OK")
    print("  PRRC judgement placeholders present and marked OK")
    print("  approved search strings rendered verbatim OK")
    print("  no list-repr leaks; state-of-art framed as non-clinical-data OK")


if __name__ == "__main__":
    main()
