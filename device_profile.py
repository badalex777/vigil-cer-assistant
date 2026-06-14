"""
Vigil - Device Profile.

The Device Profile is the abstraction layer (Pipeline Spec 6, 7.1): all
device-specificity lives in DATA, never in code. One codebase serves every
client. The profile is locked at onboarding, validated with the client, and is
IMMUTABLE during a CER run - to change scope you edit the profile and start a
new run (auditability: the PRRC must trace every output to a fixed scope).

PRRC = Person Responsible for Regulatory Compliance (MDR Art. 15) - the qualified
person at the manufacturer who reviews and signs every output.

NOTHING here is inferred by AI. This is human-defined Stage 0 input.

REGULATORY RED LINE: the equivalence register, claims, GSPR list, and evaluator
fields are CAPTURED, not judged. Vigil assembles the PRRC's input verbatim into
the CER. It never scores, validates, or concludes equivalence, benefit-risk, or
GSPR conformity - those are PRRC-only determinations (MDR Annex XIV; MDCG 2020-5).
"""
from __future__ import annotations
from dataclasses import dataclass, field, asdict
import json
import hashlib


@dataclass(frozen=True)
class EquivalentDevice:
    """One presumed-equivalent device and the PRRC's three-characteristic
    justification. Structure follows MDCG 2020-5 (the governing equivalence
    document) and MEDDEV 2.7/1 rev 4 Appendix A1.

    Equivalence may reference several devices, but per MDCG 2020-5 each must be
    justified SEPARATELY and all three characteristics (technical, biological,
    clinical) must be fulfilled for each.

    Every field here is PRRC-authored free text. Vigil stores and renders it
    verbatim into the CER equivalence section and comparative table. Vigil does
    NOT assess whether equivalence holds - that is the PRRC's determination.
    """
    name: str
    model: str = ""
    manufacturer: str = ""
    ce_marked: bool = False
    regulatory_status: str = ""
    relationship: str = ""
    technical_characteristics: str = ""
    biological_characteristics: str = ""
    clinical_characteristics: str = ""
    differences_and_justification: str = ""
    technical_documentation_access: str = ""


@dataclass(frozen=True)
class ManufacturerClaim:
    """A clinical claim the manufacturer wants the evidence to support, paired with
    the acceptance criterion / threshold that defines when the claim is met.
    Feeds the CEP and the evidence traceability matrix."""
    claim: str
    acceptance_criterion: str = ""


@dataclass(frozen=True)
class DeviceProfile:
    # --- Identity ---
    device_name: str
    manufacturer: str
    device_description: str
    intended_purpose: str
    classification: str
    classification_rule: str

    # --- Track 1: device-specific search terms (human-defined) ---
    device_synonyms: list[str] = field(default_factory=list)
    comparator_devices: list[str] = field(default_factory=list)

    # --- Track 2: state-of-the-art search terms (human-defined) ---
    medical_condition: list[str] = field(default_factory=list)
    technology_category: list[str] = field(default_factory=list)
    therapeutic_area: list[str] = field(default_factory=list)

    # --- Search protocol (locked before any search runs) ---
    date_from: str = "2015/01/01"
    date_to: str   = "2025/12/31"
    languages: list[str] = field(default_factory=lambda: ["English"])

    inclusion_criteria: list[str] = field(default_factory=list)
    exclusion_criteria: list[str] = field(default_factory=list)

    track1_inclusion_criteria: list[str] = field(default_factory=list)
    track1_exclusion_criteria: list[str] = field(default_factory=list)
    track2_inclusion_criteria: list[str] = field(default_factory=list)
    track2_exclusion_criteria: list[str] = field(default_factory=list)

    # --- Equivalence register (MDCG 2020-5 + MEDDEV A1) ---
    equivalence_claimed: bool = False
    equivalent_devices: list[EquivalentDevice] = field(default_factory=list)

    # --- Manufacturer claims + acceptance criteria ---
    manufacturer_claims: list[ManufacturerClaim] = field(default_factory=list)

    # --- PICO (MEDDEV 2.7/1 rev 4 Appendix A5) ---
    pico_population: str = ""
    pico_intervention: str = ""
    pico_comparator: str = ""
    pico_outcomes: str = ""

    # --- GSPR identification (MDR Annex I) - identification ONLY ---
    relevant_gspr: list[str] = field(default_factory=list)

    # --- Evaluator (MDR Annex XIV: evaluation by a qualified person) ---
    evaluator_name: str = ""
    evaluator_qualifications: str = ""
    declaration_of_interest_ref: str = ""

    # --- Legacy device (MDCG 2020-6) ---
    # A legacy device was CE-marked under MDD/AIMDD and is transitioning to MDR.
    # When True, the CEP gains the MDCG 2020-6 Appendix II elements and the CER
    # analysis references the sufficient-clinical-evidence hierarchy (Appendix III).
    is_legacy_device: bool = False
    # MDR Art. 61(8) well-established technology flag (affects evidence sufficiency).
    is_well_established_technology: bool = False
    # MDR Art. 61(1): the required level of clinical evidence, PRRC-defined.
    required_level_of_clinical_evidence: str = ""
    # MDCG 2020-6 App II: CEP strategies (legacy). Free text the PRRC supplies/edits.
    alternative_treatments_strategy: str = ""   # MDR Art. 61(3)(c)
    pms_data_collection_strategy: str = ""       # continuing safety/performance

    profile_version: str = "2.1"

    def criteria_for_track(self, track: str) -> tuple[list[str], list[str]]:
        """Return (inclusion, exclusion) criteria for a track, falling back to the
        shared criteria if track-specific ones aren't defined. 'both' uses Track 1
        (device-specific) criteria, since a paper appearing in both tracks is being
        considered as device evidence."""
        if track == "state_of_art" and (self.track2_inclusion_criteria
                                          or self.track2_exclusion_criteria):
            return (self.track2_inclusion_criteria or self.inclusion_criteria,
                    self.track2_exclusion_criteria or self.exclusion_criteria)
        if track in ("device_specific", "both") and (self.track1_inclusion_criteria
                                                       or self.track1_exclusion_criteria):
            return (self.track1_inclusion_criteria or self.inclusion_criteria,
                    self.track1_exclusion_criteria or self.exclusion_criteria)
        return self.inclusion_criteria, self.exclusion_criteria

    def equivalent_device_names(self) -> list[str]:
        """Names of presumed-equivalent devices, for the Track 1 query builder.
        Returns names only when equivalence is actually claimed."""
        if not self.equivalence_claimed:
            return []
        return [e.name for e in self.equivalent_devices if e.name]

    def run_scope_hash(self) -> str:
        """Stable hash of the locked scope. Stamped on every output for audit
        traceability - proves which fixed scope produced which document."""
        payload = json.dumps(asdict(self), sort_keys=True).encode()
        return hashlib.sha256(payload).hexdigest()[:12]

    @classmethod
    def from_json(cls, path: str) -> "DeviceProfile":
        with open(path) as f:
            data = json.load(f)
        return cls.from_dict(data)

    @classmethod
    def from_dict(cls, data: dict) -> "DeviceProfile":
        """Build a profile from a plain dict, hydrating the nested dataclasses
        (equivalent_devices, manufacturer_claims) from their dict form."""
        data = dict(data)
        if "equivalent_devices" in data:
            data["equivalent_devices"] = [
                EquivalentDevice(**e) if isinstance(e, dict) else e
                for e in data["equivalent_devices"]
            ]
        if "manufacturer_claims" in data:
            data["manufacturer_claims"] = [
                ManufacturerClaim(**c) if isinstance(c, dict) else c
                for c in data["manufacturer_claims"]
            ]
        return cls(**data)

    def to_dict(self) -> dict:
        d = asdict(self)
        d["run_scope_hash"] = self.run_scope_hash()
        return d
