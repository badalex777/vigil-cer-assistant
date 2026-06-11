"""
Vigil - PubMed / NCBI E-utilities client.

Two-track search (MEDDEV 2.7/1 rev 4, mandatory and separate):
  Track 1 (device_specific): device name + synonyms + comparator/equivalent devices.
  Track 2 (state_of_art)    : medical condition + technology category + therapeutic area.

The two tracks are run and DOCUMENTED separately. This module only RETRIEVES and
parses; it makes no relevance judgment (that's screen.py).

E-utilities reference: https://www.ncbi.nlm.nih.gov/books/NBK25501/
This logic must be correct - the search strategy is a regulatory artifact recorded
verbatim in the search report.
"""
from __future__ import annotations
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET

import config


def _eutils_get(endpoint: str, params: dict) -> str:
    params = {**params, "tool": config.NCBI_TOOL, "email": config.NCBI_EMAIL}
    if config.NCBI_API_KEY:
        params["api_key"] = config.NCBI_API_KEY
    url = f"{config.EUTILS_BASE}/{endpoint}?{urllib.parse.urlencode(params)}"
    time.sleep(config.NCBI_RATE_DELAY)  # respect NCBI rate limits
    with urllib.request.urlopen(url, timeout=30) as resp:
        return resp.read().decode("utf-8")


def _or_block(terms: list[str], field: str = "Title/Abstract") -> str:
    """Build an OR group: ("a"[TIAB] OR "b"[TIAB])."""
    terms = [t for t in terms if t and t.strip()]
    if not terms:
        return ""
    tag = {"Title/Abstract": "tiab", "Mesh": "mh"}.get(field, "tiab")
    return "(" + " OR ".join(f'"{t}"[{tag}]' for t in terms) + ")"


def build_track_queries(profile) -> dict[str, str]:
    """Return {'device_specific': query, 'state_of_art': query}, built from the
    locked Device Profile. Date and language filters appended to both."""
    date_filter = (f'("{profile.date_from}"[Date - Publication] : '
                   f'"{profile.date_to}"[Date - Publication])')
    lang_filter = ""
    if profile.languages:
        lang_filter = "(" + " OR ".join(f"{l}[lang]" for l in profile.languages) + ")"

    # Track 1 - device-specific
    t1_device = _or_block(profile.device_synonyms + [profile.device_name])
    t1_comp = _or_block(profile.comparator_devices)
    t1_core = t1_device if not t1_comp else f"({t1_device} OR {t1_comp})"
    track1 = " AND ".join(p for p in [t1_core, date_filter, lang_filter] if p)

    # Track 2 - state of the art (condition + technology + therapeutic area)
    t2_cond = _or_block(profile.medical_condition)
    t2_tech = _or_block(profile.technology_category)
    t2_ta = _or_block(profile.therapeutic_area)
    t2_core_parts = [p for p in [t2_cond, t2_tech, t2_ta] if p]
    # condition AND (technology OR therapeutic area) keeps SOTA focused
    if t2_cond and (t2_tech or t2_ta):
        rhs = " OR ".join(p for p in [t2_tech, t2_ta] if p)
        t2_core = f"{t2_cond} AND ({rhs})"
    else:
        t2_core = " AND ".join(t2_core_parts)
    track2 = " AND ".join(p for p in [t2_core, date_filter, lang_filter] if p)

    return {"device_specific": track1, "state_of_art": track2}


def esearch(query: str, retmax: int) -> list[str]:
    # sort=relevance uses PubMed's "Best Match" ranking, which weights how CENTRAL
    # the search terms are to each paper. Without it, E-utilities returns
    # most-recent-first, which buries the foundational literature under recent
    # case reports and papers that only mention the device incidentally.
    xml = _eutils_get("esearch.fcgi", {
        "db": "pubmed", "term": query, "retmax": retmax, "retmode": "xml",
        "sort": config.PUBMED_SORT,
    })
    root = ET.fromstring(xml)
    return [e.text for e in root.findall(".//IdList/Id")]


def efetch(pmids: list[str]) -> list[dict]:
    if not pmids:
        return []
    xml = _eutils_get("efetch.fcgi", {
        "db": "pubmed", "id": ",".join(pmids), "retmode": "xml",
    })
    root = ET.fromstring(xml)
    out = []
    for art in root.findall(".//PubmedArticle"):
        pmid = art.findtext(".//PMID")
        title = art.findtext(".//ArticleTitle") or ""
        # Abstract can be multiple labeled sections
        abs_parts = []
        for ab in art.findall(".//Abstract/AbstractText"):
            label = ab.get("Label")
            text = "".join(ab.itertext())
            abs_parts.append(f"{label}: {text}" if label else text)
        abstract = " ".join(abs_parts).strip()
        journal = art.findtext(".//Journal/Title") or ""
        year = (art.findtext(".//JournalIssue/PubDate/Year")
                or art.findtext(".//JournalIssue/PubDate/MedlineDate") or "")
        doi = ""
        for idn in art.findall(".//ArticleIdList/ArticleId"):
            if idn.get("IdType") == "doi":
                doi = idn.text
        out.append({
            "pmid": pmid, "title": title, "abstract": abstract,
            "journal": journal, "year": year, "doi": doi,
        })
    return out


def run_track(query: str, track_name: str, retmax: int) -> list[dict]:
    pmids = esearch(query, retmax)
    records = efetch(pmids)
    for r in records:
        r["track"] = track_name
    return records


def dedup(records: list[dict]) -> tuple[list[dict], int]:
    """Dedup by PMID across tracks. If a paper appears in both tracks, keep the
    first occurrence and tag it 'both'. Returns (unique_records, n_duplicates)."""
    seen: dict[str, dict] = {}
    dups = 0
    for r in records:
        pmid = r["pmid"]
        if pmid in seen:
            dups += 1
            if seen[pmid]["track"] != r["track"]:
                seen[pmid]["track"] = "both"
        else:
            seen[pmid] = r
    return list(seen.values()), dups
