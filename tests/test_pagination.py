"""
Vigil - comprehensive retrieval pagination test (Block 3).

No network. Mocks pubmed._eutils_get to return synthetic esearch/efetch XML so we
can verify the history-server pagination logic:
  - retrieves ALL hits across multiple pages,
  - stops exactly at the total,
  - respects MAX_HITS_PER_TRACK (cap) and flags capped=True,
  - records correct meta (total_available, retrieved, search_date).

Run: python tests/test_pagination.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pubmed


def _make_esearch_xml(count: int) -> str:
    return (f"<eSearchResult><Count>{count}</Count>"
            f"<WebEnv>FAKE_WEBENV</WebEnv><QueryKey>1</QueryKey>"
            f"</eSearchResult>")


def _make_efetch_xml(start: int, n: int) -> str:
    arts = []
    for i in range(start, start + n):
        arts.append(
            f"<PubmedArticle><MedlineCitation><PMID>{10000+i}</PMID>"
            f"<Article><ArticleTitle>Paper number {i}</ArticleTitle>"
            f"<Abstract><AbstractText>Abstract body {i}.</AbstractText></Abstract>"
            f"<Journal><Title>Test Journal</Title></Journal></Article>"
            f"</MedlineCitation>"
            f"<PubmedData><ArticleIdList>"
            f"<ArticleId IdType='doi'>10.1000/test.{i}</ArticleId>"
            f"</ArticleIdList></PubmedData></PubmedArticle>")
    return "<PubmedArticleSet>" + "".join(arts) + "</PubmedArticleSet>"


def run_case(total_available, cap, batch, label):
    """Install a mock _eutils_get that serves `total_available` synthetic records,
    then run comprehensive retrieval with the given cap and batch size."""
    orig_get = pubmed._eutils_get
    orig_cap = pubmed.config.MAX_HITS_PER_TRACK
    orig_batch = pubmed.config.EFETCH_BATCH
    pubmed.config.MAX_HITS_PER_TRACK = cap
    pubmed.config.EFETCH_BATCH = batch

    calls = {"efetch_pages": 0}

    def fake_get(endpoint, params):
        if endpoint == "esearch.fcgi":
            return _make_esearch_xml(total_available)
        if endpoint == "efetch.fcgi":
            calls["efetch_pages"] += 1
            retstart = int(params["retstart"])
            retmax = int(params["retmax"])
            # serve only as many as actually exist from retstart
            remaining = max(0, total_available - retstart)
            n = min(retmax, remaining)
            return _make_efetch_xml(retstart, n)
        raise AssertionError(f"unexpected endpoint {endpoint}")

    pubmed._eutils_get = fake_get
    try:
        records, meta = pubmed.run_track_comprehensive(
            "fake query", "device_specific")
    finally:
        pubmed._eutils_get = orig_get
        pubmed.config.MAX_HITS_PER_TRACK = orig_cap
        pubmed.config.EFETCH_BATCH = orig_batch

    expected_retrieved = min(total_available, cap)
    assert len(records) == expected_retrieved, (
        f"{label}: got {len(records)}, expected {expected_retrieved}")
    assert meta["total_available"] == total_available, f"{label}: total mismatch"
    assert meta["retrieved"] == expected_retrieved, f"{label}: retrieved mismatch"
    assert meta["capped"] == (total_available > cap), f"{label}: capped flag wrong"
    assert meta["search_date_utc"].endswith("Z"), f"{label}: missing search date"
    # all records carry the track tag and unique PMIDs
    assert all(r["track"] == "device_specific" for r in records), f"{label}: track tag"
    assert len({r["pmid"] for r in records}) == len(records), f"{label}: dup PMIDs"
    print(f"  {label}: total={total_available} cap={cap} batch={batch} "
          f"-> retrieved={len(records)} pages={calls['efetch_pages']} "
          f"capped={meta['capped']} OK")


def main():
    print("Comprehensive pagination cases:")
    # exact multiple of batch
    run_case(total_available=10, cap=2000, batch=5, label="exact multiple")
    # non-multiple (last partial page)
    run_case(total_available=7, cap=2000, batch=3, label="partial last page")
    # cap below total -> capped
    run_case(total_available=100, cap=20, batch=7, label="capped below total")
    # single page
    run_case(total_available=4, cap=2000, batch=200, label="single page")
    # zero results
    run_case(total_available=0, cap=2000, batch=200, label="zero results")
    print("All pagination assertions passed.")


if __name__ == "__main__":
    main()
