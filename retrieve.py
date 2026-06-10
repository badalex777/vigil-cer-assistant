"""
Vigil — open-access full-text retrieval.

Goal: minimise PRRC manual work. The PRRC should only ever upload the residual
papers that have NO legal open-access copy. Everything reachable for free is
fetched and appraised automatically.

Three tiers, tried in order:
  1. PMC (PubMed Central) — if the PubMed record links a PMCID, fetch the
     open-access full text as machine-readable XML via E-utilities (efetch from
     the 'pmc' db). Cleanest source.
  2. Unpaywall — given a DOI, ask Unpaywall for a legal OA PDF location and
     download it. Covers author manuscripts, repository copies, gold OA.
  3. None found — leave the paper for the PRRC manual-upload list.

Vigil NEVER circumvents a paywall. Unpaywall only ever returns links the publisher
or author has made openly available. Anything paywalled stays manual.

Retrieval status recorded per paper (audit trail — the search report must show HOW
each full text was obtained):
    'pmc_xml'            full text from PMC open access (XML)
    'unpaywall_pdf'      OA PDF located + downloaded via Unpaywall
    'paywalled_manual'   no OA copy; awaiting PRRC upload
    'retrieval_error'    a fetch was attempted and failed; flagged for PRRC

This module returns content + status; it does NOT appraise (that's appraise.py).
Network access (NCBI, Unpaywall) is required — runs on Replit, not the chat sandbox.
"""
from __future__ import annotations
import json
import os
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET

import config


# --- low-level HTTP -----------------------------------------------------------
def _get(url: str, accept: str = None, timeout: int = None) -> bytes:
    req = urllib.request.Request(url, headers={
        "User-Agent": f"{config.NCBI_TOOL} (mailto:{config.UNPAYWALL_EMAIL})",
        **({"Accept": accept} if accept else {}),
    })
    with urllib.request.urlopen(req, timeout=timeout or config.HTTP_TIMEOUT) as r:
        return r.read()


# --- Tier 1: PMC --------------------------------------------------------------
def find_pmcid(pmid: str) -> str | None:
    """Map a PMID to a PMCID via E-utilities elink. Returns None if not in PMC."""
    params = {"dbfrom": "pubmed", "db": "pmc", "id": pmid, "retmode": "json",
              "tool": config.NCBI_TOOL, "email": config.NCBI_EMAIL}
    if config.NCBI_API_KEY:
        params["api_key"] = config.NCBI_API_KEY
    url = f"{config.EUTILS_BASE}/elink.fcgi?{urllib.parse.urlencode(params)}"
    time.sleep(config.NCBI_RATE_DELAY)
    data = json.loads(_get(url).decode("utf-8"))
    try:
        linksets = data["linksets"][0].get("linksetdbs", [])
        for ls in linksets:
            if ls.get("dbto") == "pmc" and ls.get("links"):
                return "PMC" + str(ls["links"][0])
    except (KeyError, IndexError):
        pass
    return None


def fetch_pmc_fulltext(pmcid: str) -> tuple[str | None, str | None, str | None]:
    """Fetch open-access full text from PMC. Returns (text, doi, title) where doi/
    title come from the JATS article-meta (used for identity verification). Returns
    (None, None, None) if PMC does not serve the full text openly."""
    numeric = pmcid.replace("PMC", "")
    params = {"db": "pmc", "id": numeric, "retmode": "xml",
              "tool": config.NCBI_TOOL, "email": config.NCBI_EMAIL}
    if config.NCBI_API_KEY:
        params["api_key"] = config.NCBI_API_KEY
    url = f"{config.EUTILS_BASE}/efetch.fcgi?{urllib.parse.urlencode(params)}"
    time.sleep(config.NCBI_RATE_DELAY)
    xml = _get(url).decode("utf-8", errors="replace")
    text = _pmc_xml_to_text(xml)
    doi, title = _pmc_article_meta(xml)
    if text and len(text) > 800:
        return text, doi, title
    return None, None, None


def _pmc_article_meta(xml: str) -> tuple[str | None, str | None]:
    """Extract DOI + article title from JATS <article-meta> for verification."""
    try:
        root = ET.fromstring(xml)
    except ET.ParseError:
        return None, None
    doi = None
    for aid in root.findall(".//article-meta//article-id"):
        if (aid.get("pub-id-type") or "").lower() == "doi":
            doi = (aid.text or "").strip()
            break
    title_el = root.find(".//article-meta//article-title")
    title = "".join(title_el.itertext()).strip() if title_el is not None else None
    return doi, title


def _pmc_xml_to_text(xml: str) -> str:
    """Flatten a PMC JATS XML article body into readable text (keeps section
    headings and table captions, where AE/performance data often sits)."""
    try:
        root = ET.fromstring(xml)
    except ET.ParseError:
        return ""
    parts: list[str] = []
    body = root.find(".//body")
    if body is None:
        return ""
    for el in body.iter():
        tag = el.tag.lower()
        if tag in ("title", "label", "caption"):
            t = "".join(el.itertext()).strip()
            if t:
                parts.append(f"\n## {t}")
        elif tag == "p":
            t = "".join(el.itertext()).strip()
            if t:
                parts.append(t)
        elif tag in ("th", "td"):
            t = "".join(el.itertext()).strip()
            if t:
                parts.append(t)
    return "\n".join(parts)


# --- Tier 2: Unpaywall --------------------------------------------------------
def find_oa_pdf_url(doi: str) -> str | None:
    """Ask Unpaywall for a legal OA PDF URL for this DOI. None if no OA copy."""
    if not doi:
        return None
    url = (f"{config.UNPAYWALL_BASE}/{urllib.parse.quote(doi)}"
           f"?email={urllib.parse.quote(config.UNPAYWALL_EMAIL)}")
    try:
        data = json.loads(_get(url).decode("utf-8"))
    except Exception:
        return None
    loc = data.get("best_oa_location") or {}
    return loc.get("url_for_pdf") or loc.get("url")


def download_pdf(url: str) -> bytes | None:
    try:
        data = _get(url, accept="application/pdf")
    except Exception:
        return None
    if not data or len(data) > config.MAX_PDF_BYTES:
        return None
    # Sanity: looks like a PDF?
    return data if data[:5] == b"%PDF-" else None


# --- Orchestration ------------------------------------------------------------
def retrieve_one(rec: dict) -> dict:
    """Try to obtain full text for one record via OA tiers.

    Returns {status, kind, text|pdf_bytes|None, source_url|None} where:
      kind in {'xml_text', 'pdf', None}
    """
    pmid = rec.get("pmid")
    doi = rec.get("doi")

    # Tier 1: PMC
    try:
        pmcid = find_pmcid(pmid)
        if pmcid:
            text, found_doi, found_title = fetch_pmc_fulltext(pmcid)
            if text:
                return {"status": "pmc_xml", "kind": "xml_text", "text": text,
                        "pdf_bytes": None,
                        "found_doi": found_doi, "found_title": found_title,
                        "source_url": f"https://www.ncbi.nlm.nih.gov/pmc/articles/{pmcid}/"}
    except Exception:
        pass  # fall through to Unpaywall; never hard-fail a run on one paper

    # Tier 2: Unpaywall
    try:
        pdf_url = find_oa_pdf_url(doi)
        if pdf_url:
            pdf = download_pdf(pdf_url)
            if pdf:
                return {"status": "unpaywall_pdf", "kind": "pdf", "text": None,
                        "pdf_bytes": pdf, "source_url": pdf_url}
    except Exception:
        pass

    # Tier 3: nothing legally open -> manual upload
    return {"status": "paywalled_manual", "kind": None, "text": None,
            "pdf_bytes": None, "source_url": None}


def retrieve_batch(records: list[dict], progress=lambda s: None) -> dict[str, dict]:
    """Retrieve full text for many records. Returns {pmid: retrieval_result}."""
    out = {}
    pmc = uw = manual = 0
    for i, rec in enumerate(records, 1):
        res = retrieve_one(rec)
        out[rec["pmid"]] = res
        if res["status"] == "pmc_xml":
            pmc += 1
        elif res["status"] == "unpaywall_pdf":
            uw += 1
        else:
            manual += 1
        progress(f"  [{i}/{len(records)}] PMID {rec['pmid']}: {res['status']}")
    progress(f"Auto-retrieved: PMC {pmc}, Unpaywall {uw}; manual upload needed: {manual}")
    return out
