# Vigil CER Assistant - Build Backlog

Living checklist for the demo-prototype build. Each run is independent and
reproducible; scope is immutable within a run (frozen profile + scope_hash).

Status legend: [ ] todo  [~] in progress  [x] done

---

## Demo build plan (5 blocks)

All blocks advance SMART Goal 2: demonstrable prototype by 2026-07-31.

### Block 0 - Backlog + checkpoint
- [~] Create this BACKLOG.md (living checklist + out-of-scope decisions)

### Block 1 - Device Profile expansion (foundation)
- [ ] Equivalence register (MDCG 2020-5 + MEDDEV App. A1): list of equivalent
      devices, each with identity, 3-characteristic PRRC rationale (clinical /
      technical / biological), differences+justification, technical-documentation
      access attestation. equivalence_claimed flag at profile level.
      CAPTURED, NOT JUDGED - no scoring or validation.
- [ ] Claims + acceptance criteria/thresholds.
- [ ] PICO fields (MEDDEV App. A5): population, intervention, comparator, outcomes.
- [ ] GSPR identification (Annex I IDs the PRRC marks applicable - identification only).
- [ ] Evaluator slot: name, qualifications, declaration_of_interest_ref.
- [ ] Update npwt_sample.json with a complete example incl. one fictional equivalent.
- [ ] Preserve criteria_for_track(); bump profile_version.

### Block 2 - Search strategy + approval gate (run state machine)
- [ ] Track 1 query builder pulls equivalent-device names from the equivalence
      register (not hardcoded). Track 2 unchanged.
- [ ] Count preview (esearch rettype=count) per track - free, no LLM, no download.
- [ ] Run state machine: draft -> strings_approved -> locked -> running ->
      phase_b -> complete, persisted with per-transition timestamps.
- [ ] Post-lock edits refuse. Lock stamps scope_hash + timestamp.
- [ ] Emits the data for the Literature Search Protocol (frozen here, rendered in Block 4).

### Block 3 - Comprehensive retrieval (all hits, behind the gate)
- [ ] Full pagination via PubMed history server (usehistory=y -> WebEnv/QueryKey,
      batches of 200) - all PMIDs per track, not top-N.
- [ ] Configurable safety cap (MAX_HITS_PER_TRACK) surfaced in the count preview.
- [ ] Stays behind Block 2 lock (comprehensive screening is the expensive step).

### Block 4 - Auditable output set
- [ ] Control block on every document: version, date (UTC), scope_hash, run_id,
      evaluator, profile_version.
- [ ] CEP template (MDR Annex XIV Part A + MDCG 2020-13), rendered from locked
      profile + approved strings. Downloadable the moment Start Research is pressed.
- [ ] Literature Search Protocol (crystallized at the Block 2 gate).
- [ ] Literature Search Report (enhance: PRISMA + per-database search dates + counts).
- [ ] CER first draft (expand: equivalence section = PRRC rationale verbatim +
      comparative 3-characteristic table, ASSEMBLED not judged; GSPR placeholders;
      keep existing PRRC-only placeholders).
- [ ] Evidence traceability matrix (claim -> supporting PMIDs).
- [ ] Audit trail export (formalize run_log -> CSV; slots into client QMS).
- [ ] Every document states: AI-generated first draft requiring PRRC review.

### Block 5 - Input form UI + demo flow
- [ ] Streamlit form for the full Device Profile (incl. equivalence register).
- [ ] Demo screens: profile -> strings+counts -> approve -> lock+CEP download ->
      run progress -> Phase B -> download full set.
- [ ] Minimal polish for an 8-12 min recorded demo. Optional pre-loaded demo-mode toggle.

---

## Explicitly OUT OF SCOPE for the demo (with reasons)

- **Live QMS integration** - varies per client; building integrations before paying
  clients is scope creep. Vigil emits audit-ready documents; the client archives them
  in their own QMS (ISO 13485 4.2.4/4.2.5).
- **Full PMCF plan authoring** - depends on client market data and surveillance
  strategy; not template-automatable. The PMS Monitor is the tool a client *references*
  in their PMCF plan; Vigil does not write the plan.
- **Annual update cycle** - descoped. Each run is independent and reproducible; the
  client simply runs a fresh CER whenever needed. No delta/comparison machinery.
- **Real GSPR conformity assessment** - requires device technical/lab data Vigil never
  holds. The system emits structured GSPR *placeholders* only. Concluding conformity
  would cross the red line (system never asserts compliance).

---

## Strategic note - product positioning

PMS Monitor (Vigil's second product) is positioned as the continuous surveillance
mechanism a client cites in their PMCF plan (MDR Annex XIV Part B). It is a
complementary product covering the ongoing-evidence half of the MDR clinical-evidence
lifecycle - not a feature of the CER Assistant. Pitch the pair as covering both the
certification event (CER) and the continuous cycle (PMCF/PMS).

---

## Regulatory red lines (product correctness)

1. Vigil produces first drafts and evidence descriptions, NEVER conclusions.
2. Equivalence, benefit-risk, residual-risk acceptability, GSPR conformity are
   PRRC-only. The system captures PRRC input verbatim and assembles it; it does not
   judge, validate, suggest, or score.
3. Every extracted claim traces to a source (PMID, DOI, etc.).
4. Unknown -> output "unknown", never guess. Under-claim by default.

## Governing documents (priority order)

1. MDR 2017/745, Article 61 + Annex XIV Part A (legally binding)
2. MDCG 2020-5 (equivalence - governs all equivalence design)
3. MDCG 2020-13 (CEAR / assessment template - Notified Body expectations)
4. MEDDEV 2.7/1 rev 4 (background guidance: App. A1/A4/A5/A6)
5. PRISMA 2020 (literature flow)