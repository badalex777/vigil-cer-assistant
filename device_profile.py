"""
Vigil - Device Profile.

The Device Profile is the abstraction layer (Pipeline Spec ?6, ?7.1): all
device-specificity lives in DATA, never in code. One codebase serves every
client. The profile is locked at onboarding, validated with the client, and is
IMMUTABLE during a CER run - to change scope you edit the profile and start a
new run (auditability: the PRRC must trace every output to a fixed scope).

PRRC = Person Responsible for Regulatory Compliance (MDR Art. 15) - the qualified
person at the manufacturer who reviews and signs every output.

NOTHING here is inferred by AI. This is human-defined Stage 0 input.
"""
from __future__ import annotations
from dataclasses import dataclass, field, asdict
import json
import hashlib


@dataclass(frozen=True)
class DeviceProfile:
    # --- Identity ---
    device_name: str
    manufacturer: str
    device_description: str
    intended_purpose: str
    classification: str          # "IIa" | "IIb" | "III"
    classification_rule: str     # e.g. "Rule 11", "Rule 7"

    # --- Track 1: device-specific search terms (human-defined) ---
    # Device name + synonyms, and comparator/equivalent device names.
    # The equivalence JUDGMENT stays with the PRRC; the human supplies the names.
    device_synonyms: list[str] = field(default_factory=list)
    comparator_devices: list[str] = field(default_factory=list)

    # --- Track 2: state-of-the-art search terms (human-defined) ---
    # MEDDEV 2.7/1 rev 4 requires a SECOND, separate search track on the medical
    # condition / technology category / therapeutic area, kept strictly apart
    # from device-specific evidence.
    medical_condition: list[str] = field(default_factory=list)
    technology_category: list[str] = field(default_factory=list)
    therapeutic_area: list[str] = field(default_factory=list)

    # --- Search protocol (locked before any search runs) ---
    date_from: str = "2015/01/01"     # YYYY/MM/DD
    date_to: str   = "2025/12/31"
    languages: list[str] = field(default_factory=lambda: ["English"])

    # Shared criteria (kept as a fallback for older profiles). New profiles should
    # use the per-track criteria below, because MEDDEV 2.7/1 rev 4 expects the two
    # tracks to be appraised against DIFFERENT evidence standards:
    #   - Track 1 (device-specific): primary clinical studies of the device/equivalent.
    #   - Track 2 (state of the art): per Appendix A4, the SOTA evidence base is
    #     clinical practice guidelines, consensus statements, systematic reviews,
    #     meta-analyses and HTA reviews - NOT just primary trials. Applying Track 1's
    #     "no reviews" rule to Track 2 would discard exactly the SOTA evidence.
    inclusion_criteria: list[str] = field(default_factory=list)
    exclusion_criteria: list[str] = field(default_factory=list)

    track1_inclusion_criteria: list[str] = field(default_factory=list)
    track1_exclusion_criteria: list[str] = field(default_factory=list)
    track2_inclusion_criteria: list[str] = field(default_factory=list)
    track2_exclusion_criteria: list[str] = field(default_factory=list)

    profile_version: str = "1.0"

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

    def run_scope_hash(self) -> str:
        """Stable hash of the locked scope. Stamped on every output for audit
        traceability - proves which fixed scope produced which document."""
        payload = json.dumps(asdict(self), sort_keys=True).encode()
        return hashlib.sha256(payload).hexdigest()[:12]

    @classmethod
    def from_json(cls, path: str) -> "DeviceProfile":
        with open(path) as f:
            data = json.load(f)
        return cls(**data)

    def to_dict(self) -> dict:
        d = asdict(self)
        d["run_scope_hash"] = self.run_scope_hash()
        return d
