"""
Vigil — PRISMA 2020 flow diagram (databases & registers only variant).

PRISMA 2020 = the reporting standard for systematic reviews. The flow diagram is
a credibility differentiator for the search report (Pipeline Spec §10.3). Every
count is a byproduct of the pipeline — zero extra effort.

Template: "PRISMA 2020 flow diagram for new systematic reviews which included
searches of databases and registers only" (CC BY 4.0).
"""
from __future__ import annotations
from dataclasses import dataclass, asdict


@dataclass
class PrismaCounts:
    db_records: int = 0           # Identification: records from databases
    register_records: int = 0     # registers (n=0 in V1)
    duplicates_removed: int = 0
    auto_ineligible: int = 0       # removed by automation before screening
    other_removed: int = 0
    screened: int = 0
    excluded_screening: int = 0    # excluded at title/abstract screen
    reports_sought: int = 0        # = includes routed to retrieval
    reports_not_retrieved: int = 0 # paywalled & not retrieved (V1: appraisal_incomplete)
    assessed: int = 0              # reports assessed for eligibility (full appraisal)
    excluded_eligibility: int = 0
    included: int = 0

    def as_dict(self):
        return asdict(self)


def _box(x, y, w, h, lines, fill="#ffffff", stroke="#1a1a1a"):
    rect = (f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="4" '
            f'fill="{fill}" stroke="{stroke}" stroke-width="1.2"/>')
    tspans = ""
    line_h = 16
    start_y = y + 22
    for i, ln in enumerate(lines):
        tspans += (f'<text x="{x + w/2}" y="{start_y + i*line_h}" '
                   f'font-size="12" font-family="Arial, sans-serif" '
                   f'text-anchor="middle" fill="#1a1a1a">{ln}</text>')
    return rect + tspans


def _arrow(x1, y1, x2, y2):
    return (f'<line x1="{x1}" y1="{y1}" x2="{x2}" y2="{y2}" '
            f'stroke="#1a1a1a" stroke-width="1.2" marker-end="url(#arrow)"/>')


def render_svg(c: PrismaCounts, title: str = "PRISMA 2020 flow diagram") -> str:
    W, H = 760, 640
    col_x, col_w = 60, 320       # main (left) column
    side_x, side_w = 460, 240    # exclusion (right) column
    defs = ('<defs><marker id="arrow" markerWidth="10" markerHeight="10" refX="8" '
            'refY="3" orient="auto" markerUnits="strokeWidth">'
            '<path d="M0,0 L8,3 L0,6 Z" fill="#1a1a1a"/></marker></defs>')

    # Phase labels (left rail)
    phases = [
        ("Identification", 70),
        ("Screening", 250),
        ("Included", 560),
    ]
    rail = ""
    for label, y in phases:
        rail += (f'<text x="30" y="{y}" font-size="12" font-family="Arial" '
                 f'fill="#555" transform="rotate(-90 30 {y})" '
                 f'text-anchor="middle" font-weight="bold">{label}</text>')

    boxes = []
    # Identification
    boxes.append(_box(col_x, 50, col_w, 56, [
        "Records identified from databases",
        f"(n = {c.db_records})   Registers (n = {c.register_records})",
    ], fill="#eef4fb"))
    boxes.append(_box(side_x, 50, side_w, 72, [
        "Records removed before screening:",
        f"Duplicates removed (n = {c.duplicates_removed})",
        f"Automation ineligible (n = {c.auto_ineligible})",
        f"Other (n = {c.other_removed})",
    ], fill="#f7f7f7"))

    # Screening
    boxes.append(_box(col_x, 170, col_w, 40, [
        f"Records screened (n = {c.screened})",
    ]))
    boxes.append(_box(side_x, 170, side_w, 40, [
        f"Records excluded (n = {c.excluded_screening})",
    ], fill="#f7f7f7"))

    boxes.append(_box(col_x, 260, col_w, 40, [
        f"Reports sought for retrieval (n = {c.reports_sought})",
    ]))
    boxes.append(_box(side_x, 260, side_w, 56, [
        "Reports not retrieved",
        f"(n = {c.reports_not_retrieved})  -> appraisal incomplete",
    ], fill="#f7f7f7"))

    boxes.append(_box(col_x, 350, col_w, 40, [
        f"Reports assessed for eligibility (n = {c.assessed})",
    ]))
    boxes.append(_box(side_x, 350, side_w, 40, [
        f"Reports excluded (n = {c.excluded_eligibility})",
    ], fill="#f7f7f7"))

    # Included
    boxes.append(_box(col_x, 540, col_w, 48, [
        "Studies included in review",
        f"(n = {c.included})",
    ], fill="#e8f5e9"))

    arrows = [
        _arrow(col_x + col_w/2, 106, col_x + col_w/2, 170),  # identified -> screened
        _arrow(col_x + col_w, 78, side_x, 78),               # -> removed before screening
        _arrow(col_x + col_w/2, 210, col_x + col_w/2, 260),  # screened -> sought
        _arrow(col_x + col_w, 190, side_x, 190),             # -> excluded screening
        _arrow(col_x + col_w/2, 300, col_x + col_w/2, 350),  # sought -> assessed
        _arrow(col_x + col_w, 282, side_x, 282),             # -> not retrieved
        _arrow(col_x + col_w/2, 390, col_x + col_w/2, 540),  # assessed -> included
        _arrow(col_x + col_w, 370, side_x, 370),             # -> excluded eligibility
    ]

    return (
        f'<svg viewBox="0 0 {W} {H}" xmlns="http://www.w3.org/2000/svg">'
        f'{defs}'
        f'<text x="{W/2}" y="28" font-size="15" font-family="Arial" '
        f'text-anchor="middle" font-weight="bold" fill="#1a1a1a">{title}</text>'
        f'{rail}{"".join(arrows)}{"".join(boxes)}'
        f'</svg>'
    )


def counts_from_run(records: list[dict], duplicates: int) -> PrismaCounts:
    """Derive PRISMA counts from the records table for a run."""
    db_records = len(records) + duplicates  # identified = unique + dups removed
    screened = len(records)
    included_screen = [r for r in records if r.get("screen_verdict") == "include"]
    excluded_screen = sum(1 for r in records if r.get("screen_verdict") == "exclude")
    # V1 abstracts-only: "sought for retrieval" == screened-in; "not retrieved"
    # == those flagged appraisal_incomplete; assessed == appraisal complete.
    sought = len(included_screen)
    not_retrieved = sum(1 for r in included_screen
                        if r.get("appraisal_status") == "appraisal_incomplete")
    assessed = sought - not_retrieved
    excluded_elig = 0
    included = sum(1 for r in included_screen
                   if r.get("appraisal_status") == "complete")
    return PrismaCounts(
        db_records=db_records, register_records=0,
        duplicates_removed=duplicates, auto_ineligible=0, other_removed=0,
        screened=screened, excluded_screening=excluded_screen,
        reports_sought=sought, reports_not_retrieved=not_retrieved,
        assessed=assessed, excluded_eligibility=excluded_elig,
        included=included,
    )
