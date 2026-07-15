"""
Vigil - dev-only Device Profile prefill fixture (Block 5U).

Used ONLY when config.DEMO_PREFILL is on (VIGIL_DEMO_PREFILL=1), to seed the
Device Profile form (app.py step_device_profile) for fast local iteration
during development/demos, so the test device doesn't need re-typing on every
run. The shipped product never sets that env var, so the form renders empty.

Shaped exactly like the dict step_device_profile() builds from form inputs
(same contract as DeviceProfile.from_dict) - see tests/test_wizard_logic.py's
FORM_DICT for the equivalent test fixture. Kept separate because several
values here differ (this one mirrors a real demo run's values: manufacturer,
evaluator, and the Track 2 fields), so reusing FORM_DICT directly would not
match what a PRRC actually filled in.
"""

PORTAVAC_DEMO_PROFILE = {
    "device_name": "PortaVac NPWT System",
    "manufacturer": "Acme Medical Devices Ltd",
    "device_description": (
        "Portable single-use negative pressure wound therapy system delivering "
        "controlled sub-atmospheric pressure to the wound bed."),
    "intended_purpose": (
        "Promotion of wound healing in chronic and acute wounds via controlled "
        "negative pressure."),
    "classification": "Class IIb",
    "classification_rule": "Rule 11",
    "device_synonyms": ["NPWT", "vacuum-assisted closure", "VAC"],
    "comparator_devices": [],
    "medical_condition": ["chronic wounds", "diabetic foot ulcers"],
    "technology_category": ["negative pressure wound therapy"],
    "therapeutic_area": ["wound care", "tissue viability"],
    "date_from": "2015/01/01", "date_to": "2025/12/31", "languages": ["English"],
    "track1_inclusion_criteria": [
        "Human clinical study of the device or equivalent",
        "Reports clinical safety or performance outcomes",
    ],
    "track1_exclusion_criteria": [
        "Animal or in vitro studies only",
        "Non-English without translation",
    ],
    "track2_inclusion_criteria": [
        "Characterises current standard of care for the condition",
        "Guidelines or systematic reviews",
    ],
    "track2_exclusion_criteria": [
        "Not relevant to the medical condition",
        "Editorials or opinion pieces",
    ],
    "inclusion_criteria": [
        "Human clinical study of the device or equivalent",
        "Reports clinical safety or performance outcomes",
    ],
    "exclusion_criteria": [
        "Animal or in vitro studies only",
        "Non-English without translation",
    ],
    "equivalence_claimed": True,
    "equivalent_devices": [{
        "name": "VacuHeal Pro NPWT System", "model": "VH-2000",
        "technical_characteristics": (
            "Same operating principle (controlled sub-atmospheric pressure), "
            "comparable pressure range."),
        "biological_characteristics": (
            "Same wound-contacting materials; equivalent biocompatibility profile."),
        "clinical_characteristics": "Same indication, population, and conditions of use.",
        "differences_and_justification": (
            "Minor foam pore-size difference; not expected to affect clinical "
            "performance or safety."),
        "technical_documentation_access": (
            "Public IFU and published literature only - no contractual access "
            "to technical file."),
    }],
    "manufacturer_claims": [],
    "pico_population": "adults with chronic wounds",
    "pico_intervention": "negative pressure wound therapy",
    "pico_comparator": "standard wound dressings",
    "pico_outcomes": "wound healing rate, adverse events",
    "relevant_gspr": ["GSPR 1", "GSPR 8"],
    "is_legacy_device": True,
    "is_well_established_technology": True,
    "required_level_of_clinical_evidence": (
        "Cumulative appraised literature plus PMS data, to be confirmed "
        "sufficient by the PRRC."),
    "alternative_treatments_strategy": (
        "Track 2 search plus clinical practice guidelines to benchmark against "
        "current standard of care."),
    "pms_data_collection_strategy": (
        "Continuous signal monitoring via the Vigil PMS Monitor handoff "
        "feeding the CER cycle."),
    "next_evaluation_interval": "24 months",
    "next_evaluation_justification": (
        "Well-established technology with a stable design and continuous PMS "
        "monitoring that would trigger an earlier update on any emerging signal."),
    "evaluator_name": "Dr. Jane Smith",
    "evaluator_qualifications": "MD, wound care / tissue viability, 8 yrs clinical experience",
    "declaration_of_interest_ref": "DOI-2026-001",
}
