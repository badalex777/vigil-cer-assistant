# Vigil Block 5 - Handoff for Claude Code

State as of block5L. The 6-step Streamlit wizard runs end-to-end. Phase A runs in a
background daemon thread that survives navigation. Three bugs remain in the
Research-in-Progress loading UI plus one gating miss. All four are isolated and small.

Repo: github.com/badalex777/vigil-cer-assistant
Canonical files to touch: app.py, ui_theme.py
Deploy: Replit repl @alejandromadri5, run with `streamlit run app.py --server.port 5000`
Env: VIGIL_DEMO_RETMAX=250 (internal cap for cheap testing; comprehensive in product)
ASCII-only in all .py files (em-dashes break Replit). Never `git add -A` (use named files).

---

## BUG 1 - Rotating loading phrases overlap (do not disappear)

Symptom: on step 4 (Research in Progress), the rotating fun-fact messages stack on top
of each other instead of fading one at a time. New phrases appear but old ones stay at
opacity 1.

Root cause: `ui_theme.loading_card()` renders all 8 messages in one container with a pure
CSS keyframe fade (staggered animation-delay). This works in isolation, BUT step 4 also
calls `@st.fragment(run_every=2)` (`_phase_a_progress_fragment`) every 2 seconds. Each
fragment rerun re-injects/re-renders sibling DOM and desyncs the CSS animation clocks, so
several `.loadmsg` spans land on opacity:1 simultaneously. The loading card (CSS-timed) and
the fragment (server-timed) are fighting.

Fix options (pick one, in order of preference):
  A. Drive the message from the FRAGMENT, not CSS. Since the fragment already reruns every
     2s and already reads `result["progress"]["msg"]`, just render ONE current message
     server-side inside the fragment (st.markdown a single centered line). Delete the CSS
     keyframe rotation and the multi-span loadmsgs entirely. One message, swapped by the
     fragment, no overlap possible. THIS IS THE CLEAN FIX.
  B. If keeping CSS rotation, move the loading card render INSIDE the fragment so card and
     timer share one rerun cycle - but A is simpler and more reliable.

Relevant code:
  - ui_theme.py: `loading_card()` (~line 237) + the `.loadmsgs`/`.loadmsg`/`@keyframes
    msgfade` CSS block.
  - app.py: `_PHASE_A_MESSAGES` list, `_phase_a_progress_fragment()`, and step_research
    CASE 2 where it calls `ui_theme.loading_card(load_box, "Searching", _PHASE_A_MESSAGES)`.

---

## BUG 2 - Progress bar stuck at ~50% for minutes

Symptom: bar jumps to ~50% then sits there for 5+ minutes.

Root cause: NOT broken - it is reflecting reality badly. In `_PHASE_A_STAGE_MAP` (app.py),
screening is mapped to the 50-78% band. A comprehensive (or even retmax=250 x2 tracks +
ctgov) screen is hundreds-to-thousands of Sonnet calls, several minutes, all parked in that
band. `screen.run()` now emits "Screened N/M records" every 5 papers and
`_make_progress_writer` maps that to 0.50 + (N/M)*0.28. So it SHOULD advance within the
band - verify the per-paper progress is actually flowing (check screen.py `progress=` is
wired through pipeline.py to screen.run, and that the fragment is reading
`result["progress"]["pct"]`). If it advances but slowly, widen the band and/or smooth it.

Decision already made with founder: if the bar cannot be made to advance smoothly and
look clean, REMOVE IT. Replace with: spinner + static text "Searching - this typically
takes 3-8 minutes (longer for a comprehensive search)." A clean spinner beats a stuck bar
in a regulatory demo. The bar is a nice-to-have, not a requirement. Founder's words:
"if it cant be done cleanly, delete."

Relevant code:
  - screen.py: `run(..., progress=None)` per-paper callback (every 5 papers).
  - pipeline.py: `screen.run(..., progress=progress)` wiring.
  - app.py: `_PHASE_A_STAGE_MAP`, `_make_progress_writer`, `_phase_a_progress_fragment`.

---

## BUG 3 - Equivalent-device add/remove buttons editable after lock

Symptom: after starting research (run locked), going back to Device Profile still lets you
add/remove equivalent devices.

Root cause: the 41 form widgets got `disabled=_ro`, but the dynamic equivalence buttons
were missed.

Fix: add `disabled=_ro` to both buttons.
  app.py ~line 393: `ceq1.button("+ Add another equivalent device")` -> add `, disabled=_ro`
  app.py ~line 396: `ceq2.button("- Remove last equivalent device")` -> add `, disabled=_ro`
Also consider gating the whole equivalence add/remove column behind `if not _ro:`.

---

## BUG 4 (minor) - confirm RIS uploads are frozen post-lock

step_lock_and_start now shows a read-only summary when locked (good), so the uploader is
not reachable via the normal flow. Just confirm there is no other path to ss.ris_uploads
mutation after lock. Likely already fine; verify.

---

## BUG 5 (CRITICAL - cost) - comprehensive ran by accident; FIXED in this session

Symptom: a retmax=250 run screened 3,600+ records (should be ~540). Live DB during the run:
3134 unscreened + 360 exclude + 63 include + 78 uncertain. That is comprehensive mode (all
hits), not the 250 cap. Cost was heading to $10-20 on screening alone.

Root cause: the OLD line was
  DEMO_RETMAX = int(os.getenv("VIGIL_DEMO_RETMAX", "0")) or None  # 0 = comprehensive
If the env var is missing, getenv returns "0", int("0")=0, and `0 or None` -> None, and
`retmax is None` -> comprehensive=True. So a MISSING env var silently triggered the most
expensive path. The unsafe path was the default.

Fix applied (app.py ~line 52): inverted to a safe default. Comprehensive now requires an
EXPLICIT opt-in `VIGIL_COMPREHENSIVE=1`. Missing env var -> caps at 250/track. Verified:
  env empty       -> retmax 250 (safe)
  COMPREHENSIVE=1 -> retmax None (comprehensive)

STILL TODO in Claude Code:
  - Add a hard circuit-breaker in pipeline.run_search_and_screen: after dedup, if
    len(records) > a sane ceiling (e.g. config.MAX_SCREEN_RECORDS, say 800) and NOT
    comprehensive, abort with a clear error rather than screening thousands. A product that
    bills API usage must never run unbounded screening by accident.
  - For the demo video comprehensive run, set VIGIL_COMPREHENSIVE=1 deliberately, once.
  - Confirm Replit actually propagates env vars from .replit [env] to the Streamlit process
    started by the green Run button. The founder should run `echo $VIGIL_DEMO_RETMAX` in the
    Replit Shell; if empty, the var is not reaching the process and the safe default (250)
    is what protects them now.

---

## Verification protocol (unchanged)

Before any commit:
  python3 -m py_compile app.py ui_theme.py screen.py pipeline.py
  grep -lP "[^\x00-\x7F]" app.py ui_theme.py screen.py pipeline.py   (must be empty = ASCII)
  python3 tests/test_wizard_logic.py                                  (must pass)

Then on Replit: rm -f vigil.db; pkill -9 -f streamlit; sleep 3; green Run button.

## Phase A run budget (founder asked)
retmax=250 run: expect 8-15 min, $2-5. Kill if >20 min or >$8 (loop).
Comprehensive (no retmax, for the demo video): 20-40 min, $15-25. Run once, fully debugged.
Mid-run health check (Shell, do not kill preview):
  sqlite3 vigil.db "SELECT screen_verdict, COUNT(*) FROM records GROUP BY screen_verdict;"
