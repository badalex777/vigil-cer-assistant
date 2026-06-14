"""
Vigil - RIS ingestor (Embase / Cochrane / any subscription database export).

WHY THIS EXISTS:
Embase (Elsevier) and Cochrane (Wiley) are commercial, subscription-only databases.
Their access is by institutional login/IP, NOT a user-copyable API key, and their
licences prohibit third-party automated access. So Vigil CANNOT connect to them.
The PRRC runs the search in their own subscription, exports the results as ONE RIS
file, and uploads it here. Vigil parses that file into the same record format as
PubMed/CT.gov and feeds it through the identical pipeline (dedup -> screen -> ...).

RIS is the universal bibliographic export format: Embase, Cochrane, Scopus, Web of
Science, EndNote, Zotero all speak it. Parsing RIS once unlocks ingestion from ANY
of them - the source is whatever the PRRC declares on upload.

A RIS file is plain text; each reference is a block of "TAG  - value" lines,
beginning with "TY  - <type>" and ending with "ER  -". Example:

    TY  - JOUR
    TI  - Negative pressure wound therapy for diabetic foot ulcers
    AB  - This randomised trial compared...
    JO  - Journal of Wound Care
    PY  - 2022
    DO  - 10.12968/jowc.2022.31.4.300
    AU  - Smith J
    ER  -

The PRRC OWNS the search strategy in each database (they write the Embase query
themselves - a regulatory responsibility). Vigil only ingests what they export; it
does not translate queries or judge relevance here.
"""
from __future__ import annotations
import hashlib


# RIS tag -> our field. Multiple RIS tags can map to the same concept across
# dialects (e.g. title is TI or T1; abstract AB or N2; doi DO or sometimes in
# a generic ID field). We accept the common variants.
_TITLE_TAGS = ("TI", "T1")
_ABSTRACT_TAGS = ("AB", "N2")
_JOURNAL_TAGS = ("JO", "JF", "T2", "JA")
_YEAR_TAGS = ("PY", "Y1")
_DOI_TAGS = ("DO", "DI")


def _parse_blocks(text: str) -> list[dict]:
    """Split RIS text into reference blocks of {tag: [values]}.

    Robust to: CRLF/LF line endings, BOM, blank lines, and tag lines that use
    either 'XY  - value' (standard, two spaces + dash + space) or looser spacing.
    A new reference starts at 'TY' and ends at 'ER'."""
    text = text.lstrip("\ufeff")  # strip BOM if present
    blocks: list[dict] = []
    current: dict | None = None
    last_tag: str | None = None

    for raw in text.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        line = raw.rstrip()
        if not line:
            continue
        # A RIS tag line is: a 2-char tag, optional spaces, a dash, then an optional
        # value. Detect by pattern (not by line length) so valueless tags like
        # "ER  -" are recognized and don't get mistaken for continuation lines.
        tag = None
        value = ""
        head = line[:2]
        rest = line[2:]
        if (len(line) >= 4 and head.strip() and head.isalnum()
                and rest.lstrip().startswith("-")):
            tag = head.strip().upper()
            after = rest.lstrip()[1:]   # drop the dash
            value = after.strip()

        if tag == "TY":
            # start a new reference
            if current is not None:
                blocks.append(current)
            current = {}
            last_tag = "TY"
            current.setdefault("TY", []).append(value)
        elif tag == "ER":
            if current is not None:
                blocks.append(current)
                current = None
            last_tag = None
        elif tag:
            if current is None:  # tags before any TY -> start a loose block
                current = {}
            current.setdefault(tag, []).append(value)
            last_tag = tag
        else:
            # continuation line (no tag): append to the last tag's last value
            if current is not None and last_tag and current.get(last_tag):
                current[last_tag][-1] = (current[last_tag][-1] + " " + line.strip()).strip()

    if current is not None:
        blocks.append(current)
    return blocks


def _first(block: dict, tags: tuple) -> str:
    for t in tags:
        if block.get(t):
            return block[t][0].strip()
    return ""


def _all_authors(block: dict) -> list[str]:
    out = []
    for t in ("AU", "A1", "A2"):
        out.extend(block.get(t, []))
    return [a.strip() for a in out if a.strip()]


def _derive_id(doi: str, title: str, source: str) -> str:
    """Stable id for traceability when the export has no PMID. Prefer a clean DOI;
    else a hash of source+title. Marked so it's clearly not a PubMed id."""
    if doi:
        return f"doi:{doi.lower()}"
    h = hashlib.sha1(f"{source}|{title}".encode("utf-8")).hexdigest()[:10]
    return f"ris:{h}"


def parse_ris(text: str, source: str = "ris_export",
              track: str = "device_specific") -> tuple[list[dict], dict]:
    """Parse RIS text into internal records. Returns (records, meta).

    source: free label the PRRC declares (e.g. 'embase_export', 'cochrane_export').
    track:  which search track these belong to (default device_specific).

    Each record mirrors the PubMed/CT.gov record shape so it flows through dedup,
    screening, and the rest of the pipeline unchanged. doi is populated so the
    multi-pass dedup can collapse the same study found in PubMed AND Embase.
    """
    blocks = _parse_blocks(text)
    records = []
    skipped = 0
    for b in blocks:
        title = _first(b, _TITLE_TAGS)
        if not title:
            skipped += 1   # a reference with no title is unusable for screening
            continue
        doi = _first(b, _DOI_TAGS)
        # Some databases dump the DOI into a URL or with a prefix; keep raw here,
        # the dedup layer normalizes it.
        rec = {
            "pmid": "",  # external export, no PubMed id
            "source": source,
            "entry_type": "paper",   # RIS exports are published references
            "external_id": _derive_id(doi, title, source),
            "doi": doi,
            "title": title,
            "abstract": _first(b, _ABSTRACT_TAGS),
            "journal": _first(b, _JOURNAL_TAGS),
            "year": _first(b, _YEAR_TAGS)[:4],
            "authors": _all_authors(b),
            "ris_type": _first(b, ("TY",)),
            "track": track,
        }
        records.append(rec)

    meta = {
        "source": source,
        "track": track,
        "references_in_file": len(blocks),
        "parsed": len(records),
        "skipped_no_title": skipped,
    }
    return records, meta


def parse_ris_file(path: str, source: str = "ris_export",
                   track: str = "device_specific") -> tuple[list[dict], dict]:
    """Convenience wrapper: read a .ris/.txt file from disk and parse it.
    Tolerates non-UTF-8 exports (latin-1 fallback) common from Windows tools."""
    try:
        with open(path, encoding="utf-8") as f:
            text = f.read()
    except UnicodeDecodeError:
        with open(path, encoding="latin-1") as f:
            text = f.read()
    return parse_ris(text, source=source, track=track)
