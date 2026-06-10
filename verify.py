"""
Vigil — full-text identity verification.

Before an auto-retrieved full text is appraised, confirm it is actually the paper
we think it is. A mismatched document appraised and recorded as evidence for the
wrong PMID is a silent, expensive error in a regulated CER. This is the guard.

Two signals, deterministic (no LLM judgment):
  1. DOI match (strongest) — DOIs are unique identifiers. If the record's DOI is
     present in the document (PMC article-meta, or printed in the PDF text), the
     identity is confirmed.
  2. Title similarity (fallback) — when no DOI is printed (common in older author
     manuscripts), compare the document's title / first-page text to the record
     title via sequence ratio + distinctive-token overlap.

Verdicts:
  'verified_doi'   DOI confirmed — appraise.
  'verified_title' high title match, no DOI — appraise.
  'uncertain'      partial match — DO NOT auto-appraise; route to manual.
  'mismatch'       no DOI match and title differs — DO NOT appraise; route to manual.
  'unverifiable'   no extractable identifiers (e.g. scanned PDF) — route to manual.

Hard gate for AUTO-retrieved papers (no human in the loop). For PRRC uploads the
verdict is recorded as a soft check (the human chose the file) but surfaced if it
mismatches.
"""
from __future__ import annotations
import io
import re
import difflib

# DOI syntax per Crossref recommendation.
DOI_RE = re.compile(r'10\.\d{4,9}/[-._;()/:A-Za-z0-9]+', re.IGNORECASE)

VERIFIED = {"verified_doi", "verified_title"}

# Thresholds (tuned conservatively — prefer routing to manual over a false pass).
TITLE_VERIFIED = 0.85
TITLE_UNCERTAIN = 0.55


def normalize_doi(d: str | None) -> str | None:
    if not d:
        return None
    d = d.strip().lower()
    # strip common trailing punctuation that gets glued on during extraction
    return d.rstrip(").,;]")


def _norm_title(t: str | None) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9 ]", " ", (t or "").lower())).strip()


def title_ratio(a: str | None, b: str | None) -> float:
    a, b = _norm_title(a), _norm_title(b)
    if not a or not b:
        return 0.0
    return difflib.SequenceMatcher(None, a, b).ratio()


def title_token_overlap(record_title: str | None, text: str | None) -> float:
    """Fraction of distinctive (len>3) record-title tokens present in `text`.
    Catches the case where the paper title appears as a heading on page 1."""
    rt = set(tok for tok in _norm_title(record_title).split() if len(tok) > 3)
    if not rt:
        return 0.0
    tx = set(_norm_title(text).split())
    return len(rt & tx) / len(rt)


def extract_pdf_identifiers(pdf_bytes: bytes, max_pages: int = 2) -> dict:
    """Pull a DOI + first-page text + embedded title from PDF bytes (pypdf).
    Returns {'doi', 'text_head', 'meta_title', 'extractable'}."""
    try:
        from pypdf import PdfReader
        reader = PdfReader(io.BytesIO(pdf_bytes))
        text = ""
        for page in reader.pages[:max_pages]:
            text += (page.extract_text() or "") + "\n"
        meta_title = None
        try:
            if reader.metadata and reader.metadata.title:
                meta_title = reader.metadata.title
        except Exception:
            pass
    except Exception:
        return {"doi": None, "text_head": "", "meta_title": None, "extractable": False}
    m = DOI_RE.search(text)
    stripped = text.strip()
    # Treat near-empty extraction (e.g. scanned/image-only PDF) as unextractable.
    extractable = len(stripped) >= 20
    return {"doi": m.group(0) if m else None,
            "text_head": text[:6000],
            "meta_title": meta_title,
            "extractable": extractable}


def _is_placeholder_title(t: str) -> bool:
    """Common junk values software writes into PDF metadata title fields."""
    s = (t or "").strip().lower()
    if len(s) < 8:
        return True
    junk = ("untitled", "microsoft word", "layout", "document1", "no title",
            "print", ".indd", ".doc", ".qxd", "template")
    return any(j in s for j in junk)


def verify(record: dict, found: dict) -> dict:
    """Compare a retrieved document's identifiers against the PubMed record.

    record: needs 'doi' and 'title'.
    found : {'doi'?, 'title'? (PMC), 'text_head'? (PDF), 'meta_title'? , 'extractable'?}
    Returns {'result', 'score', 'reason'}.
    """
    rec_doi = normalize_doi(record.get("doi"))
    rec_title = record.get("title")
    text = (found.get("text_head") or "")

    # 1. DOI — strongest signal.
    found_doi = normalize_doi(found.get("doi"))
    if rec_doi and found_doi and found_doi == rec_doi:
        return {"result": "verified_doi", "score": 1.0,
                "reason": "DOI in document matches record DOI"}
    if rec_doi and rec_doi in text.lower():
        return {"result": "verified_doi", "score": 1.0,
                "reason": "record DOI found in document text"}

    # 2. Title similarity — for documents that don't print a DOI.
    # Embedded PDF metadata titles are often junk ("untitled", "Microsoft Word - ...",
    # "Layout 1"), so only trust them when they look like a real title AND the
    # document text was actually extractable.
    extractable = found.get("extractable", True)
    meta_title = found.get("meta_title")
    if meta_title and (not extractable or _is_placeholder_title(meta_title)):
        meta_title = None
    found_title = found.get("title") or meta_title

    # If we couldn't extract text and have no trustworthy title, we cannot verify.
    if not extractable and not found_title:
        return {"result": "unverifiable", "score": 0.0,
                "reason": "no extractable text or identifiers in document"}

    scores = []
    if found_title:
        scores.append(title_ratio(rec_title, found_title))
    if text:
        scores.append(title_token_overlap(rec_title, text))
    score = max(scores) if scores else 0.0

    if score >= TITLE_VERIFIED:
        return {"result": "verified_title", "score": round(score, 2),
                "reason": "document title closely matches record title"}
    if score >= TITLE_UNCERTAIN:
        return {"result": "uncertain", "score": round(score, 2),
                "reason": "partial title match; identity not confirmed"}
    if not extractable:
        return {"result": "unverifiable", "score": 0.0,
                "reason": "no extractable text or identifiers in document"}
    return {"result": "mismatch", "score": round(score, 2),
            "reason": "no DOI match and title does not match"}


def verdict_for(record: dict, retrieval_result: dict) -> dict:
    """Verify a retrieval result (from retrieve.py) against its record.
    Handles both content kinds (PMC structured ids, or PDF bytes)."""
    kind = retrieval_result.get("kind")
    if kind == "pdf":
        found = extract_pdf_identifiers(retrieval_result.get("pdf_bytes") or b"")
    elif kind == "xml_text":
        found = {"doi": retrieval_result.get("found_doi"),
                 "title": retrieval_result.get("found_title"),
                 "text_head": (retrieval_result.get("text") or "")[:6000],
                 "extractable": bool(retrieval_result.get("text"))}
    else:
        return {"result": "unverifiable", "score": 0.0, "reason": "no content"}
    return verify(record, found)
