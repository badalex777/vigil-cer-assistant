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

    # Track 1 - device-specific.
    # Comparator/equivalent device names come from TWO sources, merged:
    #   1. comparator_devices (legacy free list, kept for backward compatibility)
    #   2. the equivalence register (equivalent_device_names()) - the structured,
    #      MDCG-2020-5 record. Equivalence drives the search: the literature on a
    #      claimed equivalent device is device-specific (Track 1) evidence.
    # Dedup while preserving order so the recorded query is stable/auditable.
    eq_names = []
    if hasattr(profile, "equivalent_device_names"):
        eq_names = profile.equivalent_device_names()
    comparators = list(profile.comparator_devices)
    for n in eq_names:
        if n not in comparators:
            comparators.append(n)

    t1_device = _or_block(profile.device_synonyms + [profile.device_name])
    t1_comp = _or_block(comparators)
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


def esearch_count(query: str) -> int:
    """Return ONLY the number of PubMed hits for a query - no PMIDs downloaded,
    no LLM, no appraisal. This is the cost-control preview the PRRC sees BEFORE
    approving the search and spending money on screening/appraisal.

    Uses rettype=count so NCBI returns just the <Count> element."""
    xml = _eutils_get("esearch.fcgi", {
        "db": "pubmed", "term": query, "rettype": "count", "retmode": "xml",
    })
    root = ET.fromstring(xml)
    count_text = root.findtext(".//Count")
    return int(count_text) if count_text and count_text.isdigit() else 0


def count_preview(profile) -> dict:
    """Per-track hit counts for the approval gate. Free (no LLM, no fetch).
    Returns {'device_specific': n, 'state_of_art': m, 'queries': {...}}."""
    queries = build_track_queries(profile)
    return {
        "device_specific": esearch_count(queries["device_specific"]),
        "state_of_art": esearch_count(queries["state_of_art"]),
        "queries": queries,
    }


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


def _parse_articles(xml: str) -> list[dict]:
    """Parse a PubmedArticleSet XML into record dicts. Shared by efetch (by id)
    and efetch_history (by WebEnv/QueryKey pagination)."""
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


def efetch(pmids: list[str]) -> list[dict]:
    if not pmids:
        return []
    xml = _eutils_get("efetch.fcgi", {
        "db": "pubmed", "id": ",".join(pmids), "retmode": "xml",
    })
    return _parse_articles(xml)


def run_track(query: str, track_name: str, retmax: int) -> list[dict]:
    pmids = esearch(query, retmax)
    records = efetch(pmids)
    for r in records:
        r["track"] = track_name
    return records


def esearch_history(query: str) -> tuple[int, str, str]:
    """esearch with usehistory=y. Returns (total_count, webenv, query_key).
    The history server lets us page through ALL results without re-sending the
    query each time - the PRISMA-faithful way to retrieve the full result set."""
    xml = _eutils_get("esearch.fcgi", {
        "db": "pubmed", "term": query, "retmax": 0, "retmode": "xml",
        "usehistory": "y", "sort": config.PUBMED_SORT,
    })
    root = ET.fromstring(xml)
    count = int(root.findtext(".//Count") or "0")
    webenv = root.findtext(".//WebEnv") or ""
    query_key = root.findtext(".//QueryKey") or ""
    return count, webenv, query_key


def efetch_history(webenv: str, query_key: str, retstart: int,
                   retmax: int) -> list[dict]:
    """Fetch one page of records from the history server."""
    xml = _eutils_get("efetch.fcgi", {
        "db": "pubmed", "WebEnv": webenv, "query_key": query_key,
        "retstart": retstart, "retmax": retmax, "retmode": "xml",
    })
    return _parse_articles(xml)


def run_track_comprehensive(query: str, track_name: str,
                            max_hits: int | None = None,
                            progress=lambda s: None) -> tuple[list[dict], dict]:
    """Retrieve ALL hits for a track (up to max_hits), paginating via the NCBI
    history server. Returns (records, meta) where meta records the total available,
    how many were retrieved, whether the cap was hit, and the search date - all of
    which go into the auditable search report.

    This is the comprehensive path used for a real CER. The top-N run_track stays
    for cheap diagnostics."""
    import time as _time
    max_hits = max_hits if max_hits is not None else config.MAX_HITS_PER_TRACK
    total, webenv, query_key = esearch_history(query)
    target = min(total, max_hits)
    capped = total > max_hits

    records: list[dict] = []
    retstart = 0
    while retstart < target:
        batch = config.EFETCH_BATCH
        if retstart + batch > target:
            batch = target - retstart
        page = efetch_history(webenv, query_key, retstart, batch)
        for r in page:
            r["track"] = track_name
        records.extend(page)
        retstart += batch
        progress(f"  {track_name}: retrieved {len(records)}/{target}"
                 + (" (capped)" if capped else ""))

    meta = {
        "track": track_name,
        "total_available": total,
        "retrieved": len(records),
        "capped": capped,
        "cap": max_hits,
        "search_date_utc": _time.strftime("%Y-%m-%dT%H:%M:%SZ", _time.gmtime()),
        "query": query,
    }
    return records, meta


def _norm_doi(doi: str) -> str:
    """Normalize a DOI for comparison: lowercase, strip URL prefix and whitespace."""
    if not doi:
        return ""
    d = doi.strip().lower()
    for prefix in ("https://doi.org/", "http://doi.org/", "doi:"):
        if d.startswith(prefix):
            d = d[len(prefix):]
    return d.strip()


def _norm_title(title: str) -> str:
    """Normalize a title for comparison: lowercase, collapse whitespace, drop
    punctuation. Catches the same paper indexed with trivial formatting
    differences (e.g. ahead-of-print vs final, or the same study across sources)."""
    if not title:
        return ""
    t = title.lower()
    t = "".join(ch if ch.isalnum() or ch.isspace() else " " for ch in t)
    return " ".join(t.split())


def dedup(records: list[dict]) -> tuple[list[dict], int]:
    """Collapse duplicate papers, keeping ONE per real paper. Multi-pass so the
    same study is caught even when it has different identifiers:

      1. PMID         - same PubMed record (also handles Track1/Track2 overlap).
      2. normalized DOI - same paper, different PMID (e.g. ahead-of-print vs final)
                          or the same study retrieved from a different source.
      3. normalized title - last-resort match when DOI is missing on one copy.

    When two records collapse and they came from different tracks, the survivor is
    tagged 'both' (it is relevant to device-specific AND state-of-the-art searches).
    Returns (unique_records, n_duplicates_removed) - the duplicate count feeds the
    PRISMA 'duplicates removed' box (required by PRISMA 2020).
    """
    seen_pmid: dict[str, dict] = {}
    seen_doi: dict[str, dict] = {}
    seen_title: dict[str, dict] = {}
    seen_registry: dict[str, dict] = {}
    unique: list[dict] = []
    dups = 0

    def _merge_track(survivor: dict, other: dict):
        # If the same paper was found by both tracks, mark it 'both' for the report.
        if survivor.get("track") and other.get("track") \
                and survivor["track"] != other["track"]:
            survivor["track"] = "both"

    for r in records:
        pmid = (r.get("pmid") or "").strip()
        doi = _norm_doi(r.get("doi", ""))
        title = _norm_title(r.get("title", ""))
        registry_id = (r.get("registry_id") or "").strip()
        external_id = (r.get("external_id") or "").strip()
        is_trial = r.get("entry_type") == "trial_registration"

        # Pass 0: registry id (NCT) or external id (RIS export) - same record.
        if registry_id and registry_id in seen_registry:
            dups += 1
            _merge_track(seen_registry[registry_id], r)
            continue
        if external_id and external_id in seen_registry:
            dups += 1
            _merge_track(seen_registry[external_id], r)
            continue
        # Pass 1: PMID
        if pmid and pmid in seen_pmid:
            dups += 1
            _merge_track(seen_pmid[pmid], r)
            continue
        # Pass 2: DOI (only if DOI present)
        if doi and doi in seen_doi:
            dups += 1
            _merge_track(seen_doi[doi], r)
            continue
        # Pass 3: title (only if title present and long enough). Do NOT collapse a
        # trial registration against a published paper of similar title - they are
        # different evidence types and must both be counted.
        if title and len(title) >= 15 and title in seen_title:
            prev = seen_title[title]
            if (prev.get("entry_type") == "trial_registration") == is_trial:
                dups += 1
                _merge_track(prev, r)
                continue

        # New unique record - index it under every key it has.
        unique.append(r)
        if registry_id:
            seen_registry[registry_id] = r
        if external_id:
            seen_registry[external_id] = r
        if pmid:
            seen_pmid[pmid] = r
        if doi:
            seen_doi[doi] = r
        if title and len(title) >= 15:
            seen_title[title] = r

    return unique, dups
