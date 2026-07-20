"""
Vigil - diagnostic harness (search + screen only).

Purpose: when the full pipeline returns a surprising result (e.g. 0 papers
included), this shows EXACTLY what came back from PubMed and EXACTLY why the
screener ruled the way it did - without spending money on full-text appraisal
(Opus). It runs search + abstract screening only (Sonnet, pennies).

Usage:
    python debug_run.py                 # default: 10 papers/track, screens them
    python debug_run.py 15              # 15 papers/track
    python debug_run.py 10 --no-screen  # search only, no API cost (inspect titles)
    python debug_run.py 10 --abstracts  # print fuller abstracts
    python debug_run.py --counts        # FREE: just the per-track hit counts, no fetch/screen

What to look for in the output:
  - Titles mostly NOT about the device  -> the SEARCH is returning junk.
  - Titles relevant but verdict=exclude  -> the SCREEN is too aggressive.
  - abstract=0 chars on many papers      -> efetch/parse problem (can't screen).
"""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import config
import pubmed
import screen as screen_mod
from llm import call_json, load_prompt
from device_profile import DeviceProfile

DEVICE = "devices/npwt_sample.json"
SYSTEM = "You output only valid JSON. No markdown, no preamble."


def main():
    retmax = 10
    do_screen = True
    show_abstracts = False
    counts_only = False
    for arg in sys.argv[1:]:
        if arg.isdigit():
            retmax = int(arg)
        elif arg == "--no-screen":
            do_screen = False
        elif arg == "--abstracts":
            show_abstracts = True
        elif arg == "--counts":
            counts_only = True

    profile = DeviceProfile.from_json(DEVICE)
    queries = pubmed.build_track_queries(profile)

    print("=" * 78)
    print(f"DEVICE: {profile.device_name}   (retmax={retmax}/track)")
    print("=" * 78)
    print("\n--- TRACK 1 QUERY (device-specific) ---")
    print(queries["device_specific"])
    print("\n--- TRACK 2 QUERY (state of the art) ---")
    print(queries["state_of_art"])

    # Count preview (free: no PMIDs downloaded, no LLM). This is what the PRRC
    # sees at the approval gate before any money is spent on screening/appraisal.
    print("\n--- COUNT PREVIEW (free; total PubMed hits per track) ---")
    try:
        t1_total = pubmed.esearch_count(queries["device_specific"])
        t2_total = pubmed.esearch_count(queries["state_of_art"])
        cap = config.MAX_HITS_PER_TRACK
        print(f"Track 1 (device-specific): {t1_total} total hits"
              + (f"  [EXCEEDS CAP {cap} - would be capped; refine query or proceed]"
                 if t1_total > cap else ""))
        print(f"Track 2 (state of the art): {t2_total} total hits"
              + (f"  [EXCEEDS CAP {cap} - would be capped; refine query or proceed]"
                 if t2_total > cap else ""))
        print(f"Combined (pre-dedup): {t1_total + t2_total} hits")
        print(f"Comprehensive cap per track: {cap} (config.MAX_HITS_PER_TRACK)")
        print(f"(This diagnostic run screens only the top {retmax}/track.)")
    except Exception as e:
        print(f"[count preview failed: {e}]")

    if counts_only:
        print("\n--counts flag set: stopping after the free count preview.")
        return

    print("\nSearching PubMed (live)...")
    t1 = pubmed.run_track(queries["device_specific"], "device_specific", retmax)
    t2 = pubmed.run_track(queries["state_of_art"], "state_of_art", retmax)
    records, dups = pubmed.dedup(t1 + t2)
    print(f"Track 1: {len(t1)} | Track 2: {len(t2)} | unique: {len(records)} "
          f"| duplicates: {dups}")

    empty_abstracts = 0
    verdict_counts = {"include": 0, "exclude": 0, "uncertain": 0, "(not screened)": 0}

    print("\n" + "=" * 78)
    print("PER-PAPER BREAKDOWN")
    print("=" * 78)

    for i, rec in enumerate(records, 1):
        abstract = rec.get("abstract") or ""
        if not abstract.strip():
            empty_abstracts += 1
        title = (rec.get("title") or "").strip()
        print(f"\n[{i}] PMID {rec['pmid']} | track={rec['track']} "
              f"| abstract={len(abstract)} chars | {rec.get('journal','')} "
              f"{rec.get('year','')}")
        print(f"    TITLE: {title}")
        snippet_len = 600 if show_abstracts else 200
        if abstract.strip():
            snippet = abstract[:snippet_len].replace("\n", " ")
            print(f"    ABSTRACT: {snippet}{'...' if len(abstract) > snippet_len else ''}")
        else:
            print("    ABSTRACT: [EMPTY - nothing for the screener to read]")

        if do_screen:
            stable, variable = screen_mod._fmt(profile, rec)
            result = call_json(config.MODEL_SCREEN, SYSTEM, stable, variable,
                               config.MAX_TOKENS_SCREEN)
            if result.get("_parse_error"):
                verdict = "uncertain"
                print("    VERDICT: uncertain (screen output unparseable)")
            else:
                verdict = result.get("verdict", "uncertain")
                verdict_counts[verdict] = verdict_counts.get(verdict, 0) + 1
                print(f"    VERDICT: {verdict}")
                me = result.get("matched_exclusion") or []
                mi = result.get("matched_inclusion") or []
                if mi:
                    print(f"    matched_inclusion: {mi}")
                if me:
                    print(f"    matched_exclusion: {me}")
                print(f"    rationale: {result.get('rationale','')}")
        else:
            verdict_counts["(not screened)"] += 1

    print("\n" + "=" * 78)
    print("SUMMARY")
    print("=" * 78)
    by_track = {}
    for r in records:
        by_track[r["track"]] = by_track.get(r["track"], 0) + 1
    print(f"Records by track: {by_track}")
    print(f"Empty abstracts: {empty_abstracts} / {len(records)}")
    if do_screen:
        print(f"Verdicts: {verdict_counts}")
    print("\nRead:")
    print("  - Titles mostly off-topic  -> SEARCH problem (relevance/term logic).")
    print("  - Titles on-topic but excluded -> SCREEN problem (criteria/prompt).")
    print("  - Many empty abstracts -> efetch/parse problem.")


if __name__ == "__main__":
    main()
