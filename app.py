"""
Vigil — CER Literature Review Assistant · demo UI (Streamlit), two-phase.

Run:  streamlit run app.py
Env:  ANTHROPIC_API_KEY  (required), NCBI_API_KEY / NCBI_EMAIL (optional)

Demo arc (Goal 2):
  Phase A — device profile in -> two-track PubMed search -> screen -> retrieval list
            (every included paper flagged 'appraisal incomplete').
  Phase B — PRRC uploads full-text PDFs for paywalled / hard-to-reach papers ->
            full-text MEDDEV A6 appraisal -> papers upgrade to fully appraised,
            PRISMA + draft regenerate live. THIS is the value moment to show.
"""
import os
import streamlit as st

from device_profile import DeviceProfile
import pipeline

st.set_page_config(page_title="Vigil — CER Assistant", layout="wide")
st.title("Vigil · CER Literature Review Assistant")
st.caption("AI-assisted EU MDR clinical evaluation · MEDDEV 2.7/1 rev 4 · PRISMA 2020 · "
           "first-draft only, PRRC reviews & signs")

ss = st.session_state

with st.sidebar:
    st.header("Device Profile")
    devices = [f for f in os.listdir("devices") if f.endswith(".json")]
    chosen = st.selectbox("Load a device profile", devices)
    profile = DeviceProfile.from_json(os.path.join("devices", chosen))
    st.write(f"**{profile.device_name}**")
    st.write(f"Class {profile.classification} · {profile.classification_rule}")
    st.write(f"Scope hash: `{profile.run_scope_hash()}`")
    retmax = st.slider("Papers per track (demo)", 5, 50, 30)
    if not os.getenv("ANTHROPIC_API_KEY"):
        st.warning("ANTHROPIC_API_KEY not set — Claude steps will fail.")
    st.divider()
    if st.button("① Search, screen & auto-appraise", type="primary",
                 use_container_width=True):
        logs = []
        box = st.empty()
        def prog(m):
            logs.append(m); box.code("\n".join(logs))
        with st.spinner("Phase A…"):
            ss.result = pipeline.run_search_and_screen(
                profile, retmax=retmax, progress=prog)
            ss.profile = profile
            ss.uploads = {}
    if "result" in ss and st.button("Reset", use_container_width=True):
        for k in ("result", "uploads", "profile"):
            ss.pop(k, None)
        st.rerun()

st.markdown("> **Guardrail:** Vigil produces a structured, fully-cited *first draft*. "
            "Equivalence, benefit/risk and the compliance statement are PRRC-only "
            "placeholders. The system describes evidence; it never concludes.")

if "result" not in ss:
    st.info("Load a device profile and click **① Search, screen & auto-appraise**.")
    st.stop()

r = ss.result
c = r["counts"]
appraised = [x for x in r["retrieval_list"] if x["appraisal_status"] == "complete"]
n_pmc = sum(1 for x in appraised if x.get("retrieval_source") == "pmc_xml")
n_uw = sum(1 for x in appraised if x.get("retrieval_source") == "unpaywall_pdf")
n_upload = sum(1 for x in appraised if x.get("retrieval_source") == "prrc_upload")
manual = r["manual_upload_list"]

cols = st.columns(5)
cols[0].metric("Identified", c["db_records"])
cols[1].metric("Screened", c["screened"])
cols[2].metric("Auto-appraised", n_pmc + n_uw, help="From PMC + Unpaywall open access")
cols[3].metric("Fully appraised", c["included"])
cols[4].metric("Need manual upload", len(manual))

if n_pmc + n_uw:
    st.success(f"Auto-retrieved & appraised {n_pmc + n_uw} paper(s) from open access "
               f"(PMC {n_pmc}, Unpaywall {n_uw}) — no manual work required for these.")

# ---- Phase B: residual manual upload only ----------------------------------
st.subheader("② Manual full-text upload (residual only)")
st.caption("Vigil already fetched and appraised every paper with a legal open-access "
           "copy. Only the papers below have no open-access full text. Upload the PDF "
           "for each (you supply files you're entitled to — Vigil never bypasses a "
           "paywall). Each upload gets a full MEDDEV Appendix A6 appraisal.")

if manual:
    with st.form("uploads"):
        st.write(f"**{len(manual)} paper(s) need a manual upload:**")
        files = {}
        for x in manual:
            if x.get("retrieval_source") == "auto_unverified":
                why = (f"`open-access copy found but UNVERIFIED` — "
                       f"{x.get('verification_reason','identity not confirmed')}")
            else:
                why = "`no open-access copy found`"
            st.markdown(f"{why} · **PMID {x['pmid']}** — "
                        f"{x['title']} ({x.get('journal','')}, {x.get('year','')})")
            files[x["pmid"]] = st.file_uploader(
                f"Full-text PDF for PMID {x['pmid']}", type=["pdf"],
                key=f"up_{x['pmid']}", label_visibility="collapsed")
        go = st.form_submit_button("③ Appraise uploaded papers", type="primary")
    if go:
        uploads = {pmid: f.read() for pmid, f in files.items() if f is not None}
        if not uploads:
            st.warning("No PDFs uploaded.")
        else:
            logs = []; box = st.empty()
            def prog(m):
                logs.append(m); box.code("\n".join(logs))
            with st.spinner("Full-text appraisal…"):
                ss.result = pipeline.run_fulltext_appraisal(
                    ss.profile, r["run_id"], uploads,
                    duplicates=r.get("_duplicates", 0), queries=r["queries"],
                    progress=prog)
            st.rerun()
else:
    st.info("Every included paper was retrieved automatically — no manual upload needed.")

# ---- Outputs --------------------------------------------------------------
st.subheader("Outputs")
tab1, tab2, tab3 = st.tabs(
    ["Search Report (audit artifact)", "PRISMA diagram", "CER Draft Section"])
with tab1:
    st.markdown(r["search_report"], unsafe_allow_html=True)
    st.download_button("Download search report (.md)", r["search_report"],
                       "search_report.md")
with tab2:
    st.markdown(r["prisma_svg"], unsafe_allow_html=True)
with tab3:
    if r["n_signals"]:
        st.info(f"{r['n_signals']} CER-relevant PMS signal(s) carried forward.")
    st.markdown(r["cer_section"])
    st.download_button("Download CER draft (.md)", r["cer_section"],
                       "cer_draft_section.md")

with st.expander("Search queries (verbatim — recorded in the report)"):
    st.code("Track 1 (device-specific):\n" + r["queries"]["device_specific"]
            + "\n\nTrack 2 (state of the art):\n" + r["queries"]["state_of_art"])
