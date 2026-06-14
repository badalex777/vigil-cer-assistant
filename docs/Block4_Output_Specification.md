# Vigil - Block 4 Output Specification

**Document type:** Build reference + regulatory mapping
**Status:** Agreed structure, pre-build
**Regulatory basis:** MDR 2017/745 (Annex XIV Part A); MEDDEV 2.7/1 rev 4
(Sections 7-11, Appendices A3, A4, A5, A6, A9, A10); MDCG 2020-5 (equivalence);
MDCG 2020-13 (assessment template); PRISMA 2020.

This document specifies the auditable output set the CER Literature Review Assistant
produces. For each document it separates HARD RULES (textually required by MDR/MEDDEV)
from STANDARD PRACTICE (expected by Notified Bodies though not textually mandated), and
marks what the system generates deterministically vs. what is a PRRC-only placeholder.

## Regulatory hierarchy (verified against official MDCG/MEDDEV PDFs, June 2026)

The three layers, and how Vigil uses each:
- **MDR 2017/745 = LAW (the requirements).** Article 61 + Annex XIV Part A define WHAT
  must happen (clinical evaluation, CEP, clinical evidence, PMCF, PMS outputs). This is
  the only legally binding layer.
- **MEDDEV 2.7/1 rev 4 = METHOD (how to execute).** Not legally binding, but the
  methodology Notified Bodies still use as their technical benchmark in 2026. Governs
  the 5-stage process, the two search tracks, the search protocol/report structure.
- **MDCG guidance = CURRENT INTERPRETATION (how MDR-era expectations tighten).** Governs
  equivalence (2020-5), legacy devices + sufficient-evidence hierarchy (2020-6), PMCF
  templates (2020-7/2020-8), and the NB's own scoring template (2020-13).

Vigil structures its outputs so that: requirements trace to MDR, method traces to
MEDDEV, and documents MAP to the sections of the NB's CEAR scoring template (MDCG
2020-13) so a reviewer finds each element where they expect it.

## How the NB scores the CER: MDCG 2020-13 CEAR sections

The NB completes a Clinical Evaluation Assessment Report (CEAR) when reviewing a CER.
Vigil's outputs map to its sections:
- **Section C** (device description, classification, CEP, equivalence, state of the art)
  <- our CEP + CER sections 2-4.
- **Section D** (clinical literature review) <- our Literature Search Protocol + Search
  Report + Evidence Traceability Matrix. (MDCG 2020-13 explicitly requires the NB to
  review literature-search documentation; incomplete metadata => non-conformities.)
- **Section F** (PMS, PMCF, plan for updates) <- our CER section 7 + PMS handoff.
Designing to these sections is the highest-leverage way to reduce NB queries.

## Legacy devices (MDCG 2020-6)

In scope: the target SME may hold legacy devices (CE-marked under MDD/AIMDD) in MDR
transition. When the Device Profile flags is_legacy_device, the CEP adds the legacy
elements from MDCG 2020-6 Appendix II (see Document 1) and the CER analysis references
the sufficient-clinical-evidence hierarchy (MDCG 2020-6 Appendix III, ranks 1-8).
Key red-line reinforcements from the official text:
- State of the art / similar-device data is NOT "clinical data" under the MDR (rank 6);
  it is supportive context only, and only for well-established technologies. This
  validates Track 2 as CONTEXT, never as evidence of conformity.
- "Reliance solely on complaints and vigilance is not sufficient" - the system never
  concludes conformity from PMS/vigilance data alone.

Demo decisions (locked):
- CER First Draft: full Appendix A9 structure, with AI narrative in descriptive
  sections and explicit PRRC placeholders in judgement sections.
- Format: Markdown in Block 4 (content/structure correctness); docx wrapping in Block 5.

---

## Cross-cutting: the control block (all 6 documents)

Every document opens with an identical control block that ties the whole set to one
immutable run:

- document_title, document_version
- generated_at_utc
- run_id
- scope_hash (the frozen scope; proves immutability)
- profile_version
- device_name, manufacturer
- evaluator (name, qualifications ref, declaration-of-interests ref) - PRRC-filled
- source_tool: "Vigil CER Literature Review Assistant vX.Y"

And an identical mandatory disclaimer:

> AI-GENERATED FIRST DRAFT. This document is produced by an automated assistant to
> support, not replace, the work of a qualified Person Responsible for Regulatory
> Compliance (PRRC) or clinical evaluator. It must be reviewed, completed where marked,
> and signed by that person. It is not a final regulatory deliverable until reviewed
> and signed. Vigil describes evidence; it does not conclude on safety, performance,
> equivalence, or regulatory conformity - those determinations are the manufacturer's.

Rationale: MEDDEV requires the CER be "dated and version controlled" and signed by
evaluators (Section 11, A9 item 7). The control block generalizes that discipline to
the whole evidence set, and the scope_hash makes post-hoc tampering detectable.

---

## Document 1 - CEP (Clinical Evaluation Plan)

Stage 0 (scope). Generated deterministically from the locked profile + approved search
strings. DOWNLOADABLE THE MOMENT "Start Research" is pressed - before any results exist
(a CEP by definition precedes the evaluation).

### Hard rules (MDR Annex XIV Part A.1a - the CEP "shall" include):
- Identification of the GSPRs that require support from clinical data
- The intended purpose of the device
- The intended target groups with clear indications and contra-indications
- A detailed description of the intended clinical benefits with relevant, specified
  clinical outcome parameters
- Methods to examine the qualitative and quantitative aspects of clinical safety, with
  clear reference to the determination of residual risks and side-effects
- Parameters to determine, based on the state of the art in medicine, the acceptability
  of the benefit-risk ratio
- How benefit-risk issues relating to specific aspects are to be addressed
- An indication how equivalence is to be treated (where claimed)
- An indication of whether clinical investigation / PMCF data are needed

### Standard practice:
- Align headings to MDCG 2020-13 (the assessment template NB reviewers use)
- State the two PICO questions (Track 1 device-specific, Track 2 state of the art)
- Name the evaluator and qualifications (A11 declarations of interest)
- Reference the Vigil standard search methodology version

### Legacy-device additions (MDCG 2020-6 Appendix II, when is_legacy_device):
A legacy-device CEP must additionally include (verified against the official text):
- A strategy to identify, analyse and assess ALTERNATIVE TREATMENTS (MDR Art. 61(3)(c)).
  This is the state-of-the-art as an explicit CEP strategy, not just a Track-2 search.
- A strategy and methodology to systematically COLLECT, SUMMARISE and ASSESS PMS DATA
  to demonstrate continuing safety/performance and the extent of safety/performance
  complaints observed with the legacy device. (Direct hook to Vigil PMS Monitor.)
- A definition of the required LEVEL OF CLINICAL EVIDENCE appropriate to the device and
  intended purpose (MDR Art. 61(1)). For well-established technologies (WET), the CEP
  notes the WET criteria (simple/stable design, well-known safety, long market history).
- For equivalence: evidence of equivalence per MDR Annex XIV (see Document 4).

### CEAR mapping:
This document populates CEAR Section C (device description, classification, CEP,
equivalence, state of the art).

### System-generated (deterministic, no AI):
intended purpose, target groups, indications, identified GSPRs (identification only),
equivalence-claimed flag + the named equivalent, the two PICOs, the approved search
strings per source, the databases searched with justification, date range, the
inclusion/exclusion criteria.

### PRRC placeholders (judgement - system refuses to fill):
acceptability parameters for the benefit-risk ratio; whether clinical investigation /
PMCF data are required; final benefit-risk method sign-off.

---

## Document 2 - Literature Search Protocol

Stage 1 (the PLAN, before execution). Crystallized at the Block 2 approval gate -
the strings/criteria are frozen at sign-off, so this document is a faithful record of
what was planned, not a post-hoc reconstruction.

### Hard rules (MEDDEV Appendix A5.3 - the protocol "should include"):
- The sources of data used AND a justification for their choice
- Which electronic databases are searched, WITH justification
- The exact search terms and any limits
- Start and end dates of each search
- The selection (inclusion/exclusion) criteria AND justification for their choice
- Strategies for addressing duplication of data across multiple publications
- Strategies for avoiding retrieval of data already held by the manufacturer
- The data collection plan (data-integrity / QC, e.g. second review)
- The appraisal plan (how each publication's relevance + methodological quality is judged)
- The analysis plan (how data are analysed, processed, transformed)
- Governing principle (hard): the search "should be thorough and objective, i.e. it
  should identify all relevant favourable AND unfavourable data."

### Standard practice:
- PICO-structured review questions (A5.2)
- Reference PRISMA 2020 / Cochrane Handbook as the method framework
- Document Track 1 and Track 2 separately

### CEAR mapping:
This document (with the Search Report and Traceability Matrix) populates CEAR Section D
(clinical literature review). MDCG 2020-13 explicitly requires the NB to review
literature-search documentation; incomplete search metadata is a common source of
non-conformities, so the protocol's metadata must be complete.

### System-generated (deterministic):
both PICOs; per-source search strings verbatim (PubMed, ClinicalTrials.gov, and any
PRRC-declared subscription-database queries for Embase/Cochrane via RIS); date limits;
the LOCKED inclusion/exclusion criteria; the multi-pass dedup strategy; sources +
justification text (from the Vigil methodology doc); the appraisal + analysis plan
(standard methodology). The "avoid manufacturer-held data duplication" strategy:
manufacturer data enters tagged separately and is appraised alongside, not re-searched.

### PRRC placeholders:
none structural - but the PRRC owns and must approve every element before lock. For
subscription databases the PRRC writes their own query (they own that search strategy);
Vigil records what they declare, it does not translate it.

---

## Document 3 - Literature Search Report

Stage 1 (what actually HAPPENED on execution). MEDDEV separates this from the protocol:
"a literature search report should be compiled to present details of the execution, any
deviations from the protocol, and the results."

### Hard rules:
- Details of the execution
- ANY deviations from the search protocol
- The results of the search
- Documented so "the methods can be appraised critically, the results can be verified,
  and the search reproduced if necessary" (reproducibility is required)

### Standard practice (strong - de facto expected):
- PRISMA 2020 flow diagram with counts at EVERY stage
- Per-database search date and per-database hit counts
- Explicit accounting of records lost at each step, e.g. "X identified / Y retrieved /
  Z not-retrievable" (the 347-identified / 346-retrieved / 1-not-retrievable case we
  observed live - this transparency is exactly what PRISMA wants)

### System-generated (deterministic - 100% of this document):
per-source search dates; counts per database; comprehensive-retrieval totals incl.
capped flags; duplicates removed (multi-pass); records screened; include/exclude/
uncertain counts; auto-retrieved open-access full texts; identity-verification
results; paywalled residuals routed to PRRC; PRRC-reviewed counts; final included.
The full PRISMA 2020 flow diagram with every box populated.

### PRRC placeholders:
deviations narrative (if the PRRC departed from the protocol, they note why); any
supplementary manual searches they ran outside Vigil.

---

## Document 4 - CER First Draft

Stages 2-4 (appraisal, analysis, report). Structure follows Appendix A9. The only
document where AI writes narrative. Descriptive sections get AI prose; judgement
sections get explicit PRRC placeholders.

### Hard rules (A9 / A10 / Section 11):
- Dated, version-controlled, and signed by the evaluators with CV + declaration of
  interests (A9 item 7; Section 11)
- If equivalence is claimed: include the demonstration of equivalence; DISCLOSE ALL
  differences between the device and the equivalent; EXPLAIN why the differences are
  not expected to affect clinical performance and safety (A10)
- State of the art substantiated by literature (A10)
- Explain why the benefit-risk profile and undesirable side-effects are acceptable in
  relation to the state of the art (A10)
- Readable and understandable by a third party, with sufficient detail of data,
  assumptions, and conclusions (A10)

### Vigil red lines (non-negotiable - describe, never conclude):
- Equivalence section: the system ASSEMBLES the 3-characteristic comparison table
  (technical / biological / clinical, per MDCG 2020-5) and transcribes the PRRC's
  equivalence rationale VERBATIM. It does NOT judge whether equivalence holds.
- Benefit-risk acceptability, residual-risk acceptability, GSPR conformity: explicit
  PRRC-only placeholders. The AI refuses to conclude.
- State of the art (Track 2) is presented as CONTEXT, explicitly labelled as NOT
  constituting clinical data under the MDR (MDCG 2020-6, rank 6). The system never
  treats it as evidence of conformity.
- The CER never concludes conformity from PMS/vigilance data alone (MDCG 2020-6:
  "reliance solely on complaints and vigilance is not sufficient").

### Legacy-device additions (when is_legacy_device):
- Section 6 (analysis) references the sufficient-clinical-evidence hierarchy (MDCG
  2020-6 Appendix III, ranks 1-8) and tags each evidence source by its rank, so the
  PRRC can assess whether the cumulative evidence meets the required level for the GSPRs.
- For WET devices, notes that cumulative evidence from lower-rank sources may suffice
  if appropriately appraised - a PRRC judgement, surfaced not concluded.

### CEAR mapping:
CER sections 2-4 populate CEAR Section C; section 7 (PMCF/PMS) populates CEAR Section F.

### A9 table of contents (the structure we generate):
1. Summary
2. Scope of the clinical evaluation (from CEP)
3. Clinical background, current knowledge, state of the art (AI narrative from Track 2)
4. Device under evaluation
   - 4.1 Device description + intended purpose (deterministic from profile)
   - 4.2 Equivalence (if claimed): comparison table assembled + PRRC rationale verbatim
         + [PRRC JUDGEMENT: equivalence determination]
   - 4.3 Manufacturer-held clinical data summary (if uploaded)
5. Summary of the clinical data and appraisal (AI narrative from appraised full texts,
   each claim cited to PMID/source)
6. Analysis of the clinical data
   - 6.1 Performance (descriptive summary of evidence)
   - 6.2 Safety (descriptive summary of evidence)
   - 6.3 [PRRC JUDGEMENT: benefit-risk acceptability vs state of the art]
   - 6.4 [PRRC JUDGEMENT: residual-risk acceptability]
   - 6.5 [PRRC JUDGEMENT: GSPR conformity]
7. PMCF / PMS considerations (CER-relevant PMS signals surfaced; PRRC plans PMCF)
8. Conclusions [PRRC JUDGEMENT - the system does not write conclusions]
9. Dates and signatures (control block + evaluator sign-off slots)
10. References (auto-assembled from cited sources)

### System-generated (deterministic + AI narrative in descriptive sections only):
device description, scope, state-of-the-art narrative, appraised-evidence summaries
with citations, the equivalence comparison table, references list, PMS signals.

### PRRC placeholders (every judgement):
equivalence determination, benefit-risk acceptability, residual-risk acceptability,
GSPR conformity, conclusions, evaluator sign-off.

---

## Document 5 - Evidence Traceability Matrix

Audit support. NOT a MEDDEV-named document - standard quality practice and an
auditability differentiator. Operationalizes the MEDDEV principle that every claim is
traceable to source and that the NB can verify results.

### Content (100% deterministic):
one row per substantive CER claim -> the supporting record id(s) (PMID / NCT / RIS
external_id), source type (Published Literature / Manufacturer-Held Data / Trial
Registration / PMS Signal), track, and appraisal status. Lets an auditor jump from any
sentence in the CER to its evidence in one step.

---

## Document 6 - Audit Trail Export

Audit / QMS support. NOT MEDDEV-named; fits the client's ISO 13485 4.2.4/4.2.5 record
control. Formalizes the run_log to CSV.

### Content (100% deterministic):
every state transition with UTC timestamp (draft -> strings_approved -> locked ->
running -> phase_b -> complete); who approved the strings; the scope_hash; every PRRC
relevance override with its preserved original classification, rationale, and timestamp.
Proves the process was controlled and not tuned post-hoc.

---

## Build order within Block 4

1. Shared control-block + disclaimer renderer (used by all 6).
2. CEP (deterministic; downloadable at lock) - validates the control block first.
3. Literature Search Protocol (deterministic, from approved strings).
4. Literature Search Report (deterministic, incl. PRISMA flow - extends existing prisma.py).
5. Evidence Traceability Matrix (deterministic).
6. Audit Trail Export (deterministic CSV).
7. CER First Draft (A9 structure; AI narrative + placeholders) - last, the most complex.

Verification gate (offline): generate the full set on the offline fixture; assert every
document carries the control block + disclaimer; assert CEP renders from profile alone
(no results needed); assert every judgement placeholder is present and clearly marked;
assert traceability rows map only to retrieved record ids.
