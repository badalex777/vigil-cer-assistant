"""
Vigil — central configuration.

All tunable constants live here so model choices, rate limits, and date ranges
are changed in ONE place. Per architecture: prompt templates are external/versioned
(see prompts/), model selection is justified per workflow.
"""
import os

# --- Anthropic models (current public strings, June 2026) ---------------------
# Rationale (Vigil Pipeline Spec §16):
#   - Bulk abstract screening: high volume, lower per-item stakes -> faster/cheaper Sonnet.
#   - Abstract-level extraction: PRELIMINARY pass, overwritten by full-text appraisal
#     where a paper is retrieved -> Sonnet (cost-conscious; this result only persists
#     for papers that never get full text, where it's flagged appraisal-incomplete anyway).
#   - Full-text APPRAISAL + extraction: compliance-critical, long-document reasoning,
#     the result that carries citations into the CER -> Opus. This is where accuracy matters.
MODEL_SCREEN   = os.getenv("VIGIL_MODEL_SCREEN",   "claude-sonnet-4-6")
MODEL_EXTRACT  = os.getenv("VIGIL_MODEL_EXTRACT",  "claude-sonnet-4-6")   # abstract pass
MODEL_APPRAISE = os.getenv("VIGIL_MODEL_APPRAISE", "claude-opus-4-8")     # full-text pass
MODEL_DRAFT    = os.getenv("VIGIL_MODEL_DRAFT",    "claude-opus-4-8")

ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
MAX_TOKENS_SCREEN   = 1024
MAX_TOKENS_EXTRACT  = 4096
MAX_TOKENS_APPRAISE = 8192
MAX_TOKENS_DRAFT    = 8192

# Where the PRRC's uploaded full-text PDFs are stored (per run, per PMID).
UPLOADS_DIR = os.getenv("VIGIL_UPLOADS", "uploads")

# --- NCBI E-utilities ---------------------------------------------------------
# A free NCBI key raises the rate limit from 3 to 10 requests/sec. Optional but
# recommended. Get one at https://www.ncbi.nlm.nih.gov/account/settings/
NCBI_API_KEY = os.getenv("NCBI_API_KEY", "")
NCBI_EMAIL   = os.getenv("NCBI_EMAIL", "alejandro@vigil.example")  # E-utils etiquette
NCBI_TOOL    = "vigil-cer-assistant"
EUTILS_BASE  = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"
NCBI_RATE_DELAY = 0.34 if NCBI_API_KEY else 0.11  # seconds between calls (with/without key); see note
# Note: with a key NCBI allows 10 req/s (0.10s); without, 3 req/s (0.34s). The
# values above are intentionally conservative. Swap if you hit rate limits.

# --- Auto full-text retrieval (open access only) ------------------------------
# Tier 1: PMC (PubMed Central) open-access — full text via NCBI itself.
# Tier 2: Unpaywall — given a DOI, returns a LEGAL open-access PDF location if one
#         exists. Free; requires an email. https://unpaywall.org/products/api
# Tier 3 (no OA found): routed to the PRRC manual-upload list. Vigil never bypasses
#         a paywall — the PRRC supplies files they are entitled to.
ENABLE_AUTO_RETRIEVAL = os.getenv("VIGIL_AUTO_RETRIEVAL", "1") == "1"
UNPAYWALL_BASE  = "https://api.unpaywall.org/v2"
UNPAYWALL_EMAIL = os.getenv("UNPAYWALL_EMAIL", NCBI_EMAIL)
RETRIEVAL_CACHE_DIR = os.getenv("VIGIL_RETRIEVAL_CACHE", "retrieval_cache")
MAX_PDF_BYTES = 25 * 1024 * 1024  # skip absurdly large files; flag for manual review
HTTP_TIMEOUT = 45


# --- Run defaults -------------------------------------------------------------
DEFAULT_RETMAX_PER_TRACK = 30   # demo target: ~20-30 papers/track
DB_PATH = os.getenv("VIGIL_DB", "vigil.db")

# --- Prompt template versions (external, versioned) ---------------------------
PROMPT_SCREEN   = "prompts/screen_v1.txt"
PROMPT_EXTRACT  = "prompts/extract_v1.txt"
PROMPT_APPRAISE = "prompts/appraise_fulltext_v1.txt"
PROMPT_DRAFT    = "prompts/draft_section_v1.txt"
