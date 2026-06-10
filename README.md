# Vigil — CER Literature Review Assistant (prototype v0.1)

AI-assisted EU MDR clinical evaluation literature review. Takes a locked **Device
Profile**, runs a **two-track PubMed search** (device-specific + state-of-the-art),
screens abstracts, extracts adverse-event/performance data, and produces **two
outputs**: an audit-ready **search report** (with verbatim queries + a PRISMA 2020
flow diagram) and a **MEDDEV 2.7/1 rev 4-aligned CER first-draft section**.

**Acronyms:** MDR = Medical Device Regulation (EU 2017/745). CER = Clinical
Evaluation Report. MEDDEV 2.7/1 rev 4 = the EU guidance for clinical evaluation.
PRRC = Person Responsible for Regulatory Compliance (the qualified person who
reviews and signs). PRISMA 2020 = systematic-review reporting standard.

> **Guardrail:** Vigil produces a fully-cited *first draft*. Equivalence,
> benefit/risk, residual-risk, and compliance statements are **PRRC-only
> placeholders**. The system describes evidence; it never concludes.

## What's real vs. stubbed (v0.1)

| Piece | State |
|---|---|
| Two-track query builder from Device Profile | ✅ real, valid E-utilities syntax |
| PubMed esearch + efetch + dedup | ✅ real (needs NCBI network — runs on Replit, not in chat sandbox) |
| Abstract screening (Claude Sonnet) | ✅ real |
| Abstract-level extraction (Claude Sonnet) | ✅ real — preliminary pass, flags `appraisal_incomplete` |
| **Auto-retrieval of open-access full text (PMC + Unpaywall)** | ✅ **real — the default; minimises manual work** (needs network → Replit) |
| **Identity verification gate (DOI / title) before appraisal** | ✅ **real — wrong/unconfirmed docs are blocked, not appraised** |
| **PRRC full-text upload + MEDDEV A6 appraisal (Claude Opus, PDF/text)** | ✅ **real — residual fallback for no-OA / unverified papers** |
| PRISMA 2020 SVG from pipeline counts | ✅ real, updates between phases |
| Search report + CER draft assembly | ✅ real, records retrieval source + verification per paper |
| PMS Monitor write-side + shared signals table | ◐ table + CER read-path exist; PMS write-side is the next build |
| Billing / auth / multi-tenant | ✗ out of scope by design |

## Identity verification (why a retrieved PDF is trusted)

Before any auto-retrieved full text is appraised, Vigil confirms it is the paper
it claims to be — a wrong document appraised as evidence for the wrong PMID is a
silent, expensive error in a regulated CER. Two independent layers:

1. **Deterministic gate (primary).** Confirm the record's **DOI** appears in the
   document (PMC article-meta, or printed in the PDF). DOIs are unique, so a match
   is conclusive and audit-defensible. No DOI printed → fall back to **title
   similarity** (sequence ratio + distinctive-token overlap). For auto-retrieval
   this is a HARD gate: `mismatch` / `uncertain` / `unverifiable` → the paper is
   NOT appraised and drops to the manual-upload list, flagged with the reason.
2. **LLM self-check (defense in depth).** The appraisal prompt instructs Claude to
   refuse and flag if the document doesn't match the expected PMID/title.

PRRC uploads are verified as a *soft* check: the verdict is recorded in the audit
trail and a mismatch is surfaced, but the upload is still appraised (a human chose
the file). The search report records, per paper, both how the full text was
obtained (PMC / Unpaywall / upload) and how its identity was verified (DOI / title).

## The workflow (this is the product)

```
PHASE A  search → screen → abstract pass
         → AUTO-RETRIEVE full text for every included paper:
              tier 1  PMC open access        (full text as XML/text)
              tier 2  Unpaywall              (legal OA PDF by DOI)
              tier 3  no OA found            → manual-upload list (residual only)
         → VERIFY identity of each retrieved doc (DOI / title)
              verified    → appraise
              unverified  → manual-upload list (flagged with reason)
         → AUTO-APPRAISE (MEDDEV A6) the verified docs
         → outputs + a SHORT manual-upload list

PHASE B  PRRC uploads PDFs for the residual (no-OA / unverified) papers only
         → MEDDEV A6 appraisal → papers upgrade to fully appraised
         → PRISMA + draft regenerate
```

The burden is inverted: at 150 papers, the PRRC uploads only the handful with no
legal open-access copy, not all 150. Every full text is appraised the same way
regardless of source; the search report records **how** each was obtained (PMC /
Unpaywall / PRRC upload) for the audit trail. Vigil never circumvents a paywall —
Unpaywall only returns links the publisher or author made openly available.

**No new dependencies:** retrieval uses the Python standard library (`urllib`).

## Run on Replit

1. Upload this folder. In **Secrets**, set `ANTHROPIC_API_KEY` (and optionally
   `NCBI_API_KEY`, `NCBI_EMAIL`).
2. `pip install -r requirements.txt`
3. `streamlit run app.py`
4. Pick `npwt_sample.json`, click **① Run search & screening**, then upload a
   full-text PDF for an included paper and click **③ Run full-text appraisal**.

## Run the offline demo (no keys, no network)

```
python tests/offline_demo.py
```
Exercises BOTH phases (search/screen + a simulated PDF upload & appraisal) with
canned NPWT abstracts and a fake LLM. Use as a **demo fallback** if PubMed is flaky
on a prospect call. Writes artifacts to `/tmp/vigil_*.{md,svg}`.

## Swap in a different device

Copy `devices/npwt_sample.json`, edit the fields (all human-defined — nothing is
AI-inferred), drop it in `devices/`. Device-specificity lives in **data, not code**.

## Files

```
config.py            model strings, rate limits, prompt paths (one place to tune)
device_profile.py    DeviceProfile dataclass (immutable per run, scope hash for audit)
pubmed.py            two-track query builder + E-utilities client + dedup
db.py                SQLite: records / outputs / shared signals / run_log + state setters
llm.py               Anthropic wrapper: call_json, call_text, call_json_pdf (native PDF)
prompts/             screen_v1 / extract_v1 / appraise_fulltext_v1 / draft_section_v1
screen.py            Phase A — abstract relevance screening (Sonnet)
extract.py           Phase A — abstract-level extraction; flags appraisal_incomplete (Sonnet)
retrieve.py          Phase A — open-access full-text retrieval (PMC + Unpaywall tiers)
verify.py            Phase A — identity verification gate (DOI / title) before appraisal
appraise.py          Phase B — full-text MEDDEV A6 appraisal (PDF native + PMC text) (Opus)
prisma.py            PRISMA 2020 flow diagram (SVG) from counts
draft.py             search report (deterministic) + CER draft (LLM, cited)
pipeline.py          two-phase orchestrator: run_search_and_screen / run_fulltext_appraisal
app.py               Streamlit two-phase demo UI (upload PDFs between phases)
tests/offline_demo.py  no-network end-to-end test (retrieval + verification + both phases)
tests/test_verify.py   unit test for the verification gate, on REAL generated PDFs
```

→ This advances **Goal 2** (demonstrable prototype, deadline July 31). The 8–12 min
demo recording records a real device profile going in and the two output documents
coming out.
