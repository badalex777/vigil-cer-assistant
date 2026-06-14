"""
Vigil - ClinicalTrials.gov API v2 client (second search source).

WHY THIS IS A SEPARATE MODULE FROM pubmed.py:
A ClinicalTrials.gov record is NOT a published paper. It is a TRIAL REGISTRATION:
a protocol + recruitment status + (sometimes) posted results. Its evidence role in
a CER is different from a PubMed abstract:
  - PubMed gives evidence of OUTCOMES (a completed, peer-reviewed study).
  - CT.gov gives evidence that a study EXISTS - including studies that were never
    published. Searching it is how a CER demonstrates it looked for unpublished /
    unfavourable evidence (publication-bias check, expected by Notified Bodies).

So these records carry source='clinicaltrials_gov' and entry_type='trial_registration'
and are screened with their own logic - never treated as equivalent to a paper.

API v2 (free, no auth): https://clinicaltrials.gov/data-api/api
  GET https://clinicaltrials.gov/api/v2/studies?query.cond=...&query.intr=...
  Pagination via nextPageToken. Data lives under each study's protocolSection.

The query SYNTAX here is CT.gov-specific (query.cond / query.intr), NOT PubMed's
[tiab] syntax. The two sources are searched and DOCUMENTED separately - the search
report records each source's own query verbatim.
"""
from __future__ import annotations
import json
import time
import urllib.parse
import urllib.request

import config

CTGOV_BASE = "https://clinicaltrials.gov/api/v2/studies"


def build_ctgov_query(profile) -> dict:
    """Build CT.gov query parameters from the Device Profile.

    CT.gov uses condition (query.cond) and intervention (query.intr) rather than
    free Boolean over title/abstract. We derive:
      - condition  from medical_condition (Track 2 vocabulary) or PICO population
      - intervention from technology_category + device synonyms + comparators
    Returns the param dict (without paging/format), plus a 'human' string for the
    search report.
    """
    conditions = list(profile.medical_condition)
    if not conditions and profile.pico_population:
        conditions = [profile.pico_population]

    interventions = list(profile.technology_category) + list(profile.device_synonyms)
    # include equivalents/comparators - trials of an equivalent device are relevant
    if hasattr(profile, "equivalent_device_names"):
        interventions += profile.equivalent_device_names()
    interventions += list(profile.comparator_devices)

    cond = " OR ".join(c for c in conditions if c)
    intr = " OR ".join(i for i in interventions if i)

    params = {}
    if cond:
        params["query.cond"] = cond
    if intr:
        params["query.intr"] = intr
    human = f"condition=({cond}) AND intervention=({intr})"
    return {"params": params, "human": human}


def _ctgov_get(params: dict) -> dict:
    url = f"{CTGOV_BASE}?{urllib.parse.urlencode(params)}"
    req = urllib.request.Request(url, headers={"Accept": "application/json"})
    time.sleep(config.NCBI_RATE_DELAY)  # be polite; reuse the existing rate delay
    with urllib.request.urlopen(req, timeout=config.HTTP_TIMEOUT) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _map_study(study: dict) -> dict:
    """Map one CT.gov study JSON into the internal record format, flagged as a
    trial registration (not a paper). Fields chosen to flow through screening."""
    proto = study.get("protocolSection", {})
    idm = proto.get("identificationModule", {})
    status = proto.get("statusModule", {})
    desc = proto.get("descriptionModule", {})
    design = proto.get("designModule", {})
    conds = proto.get("conditionsModule", {})

    nct = idm.get("nctId", "")
    title = idm.get("briefTitle") or idm.get("officialTitle") or ""
    summary = desc.get("briefSummary", "") or ""
    overall_status = status.get("overallStatus", "")
    has_results = study.get("hasResults", False)
    enrollment = (design.get("enrollmentInfo", {}) or {}).get("count")
    study_type = design.get("studyType", "")
    phases = ", ".join(design.get("phases", []) or [])
    condition_list = ", ".join(conds.get("conditions", []) or [])
    start_year = (status.get("startDateStruct", {}) or {}).get("date", "")[:4]

    # The 'abstract' field is what the screener reads; for a registration we
    # synthesize a structured summary so the screener has the registry facts and
    # can apply trial-registration logic (existence vs published outcomes).
    abstract = (
        f"[CLINICAL TRIAL REGISTRATION - not a published paper] "
        f"Status: {overall_status}. Study type: {study_type}. "
        f"Phase: {phases or 'N/A'}. Enrollment: {enrollment or 'unknown'}. "
        f"Conditions: {condition_list}. "
        f"Results posted on registry: {'yes' if has_results else 'no'}. "
        f"Summary: {summary}"
    ).strip()

    return {
        "pmid": "",                     # not a PubMed record
        "source": "clinicaltrials_gov",
        "entry_type": "trial_registration",
        "registry_id": nct,             # NCT id (traceability, like a PMID)
        "doi": "",
        "title": title,
        "abstract": abstract,
        "journal": "ClinicalTrials.gov",
        "year": start_year,
        "overall_status": overall_status,
        "has_results": bool(has_results),
        "enrollment": enrollment,
        "study_type": study_type,
        "registry_url": f"https://clinicaltrials.gov/study/{nct}" if nct else "",
    }


def run_ctgov(profile, track_name="device_specific", max_hits=None,
              progress=lambda s: None) -> tuple[list[dict], dict]:
    """Search ClinicalTrials.gov and return (records, meta). Records are tagged as
    trial registrations. Paginates via nextPageToken up to max_hits (defaults to
    config.MAX_HITS_PER_TRACK)."""
    max_hits = max_hits if max_hits is not None else config.MAX_HITS_PER_TRACK
    q = build_ctgov_query(profile)
    base_params = {
        **q["params"], "format": "json", "pageSize": 100, "countTotal": "true",
    }

    records: list[dict] = []
    total = None
    page_token = None
    capped = False
    while True:
        params = dict(base_params)
        if page_token:
            params["pageToken"] = page_token
        data = _ctgov_get(params)
        if total is None:
            total = data.get("totalCount", 0)
        for study in data.get("studies", []):
            rec = _map_study(study)
            rec["track"] = track_name
            records.append(rec)
            if len(records) >= max_hits:
                capped = True
                break
        progress(f"  CT.gov: retrieved {len(records)}"
                 + (f"/{total}" if total is not None else "")
                 + (" (capped)" if capped else ""))
        page_token = data.get("nextPageToken")
        if capped or not page_token:
            break

    meta = {
        "source": "clinicaltrials_gov",
        "track": track_name,
        "total_available": total or 0,
        "retrieved": len(records),
        "capped": capped,
        "cap": max_hits,
        "search_date_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "query": q["human"],
    }
    return records, meta
