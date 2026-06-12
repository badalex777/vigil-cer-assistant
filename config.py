"""
Vigil - central configuration.

All tunable constants live here so model choices, rate limits, and date ranges
are changed in ONE place. Per architecture: prompt templates are external/versioned
(see prompts/), model selection is justified per workflow.
"""
import os

# --- .env loader (stdlib only, no pip install required) ----------------------
# Loads key=value pairs from a .env file in the project root into os.environ
# BEFORE any os.getenv() calls below. Variables already set in the environment
# take priority (shell exports or Replit Secrets win if present; .env is the
# reliable fallback so the app works in any fresh Shell without manual export).
def _load_dotenv(path=".env"):
    try:
        with open(path) as fh:
            for raw in fh:
                line = raw.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, _, val = line.partition("=")
                key = key.strip()
                val = val.strip()
                if len(val) >= 2 and val[0] == val[-1] and val[0] in (chr(39), chr(34)):
                    val = val[1:-1]
                if key and key not in os.environ:
                    os.environ[key] = val
    except FileNotFoundError:
        pass  # .env is optional; shell exports still work

_load_dotenv()

# --- Anthropic models (current public strings, June 2026) ---------------------
# Rationale (Vigil Pipeline Spec 16):
#   - Bulk abstract screening: high volume, lower per-item stakes -> Sonnet.
#   - Abstract-level extraction: PRELIMINARY pass, overwritten by full-text
#     appraisal where a paper is retrieved -> Sonnet (cost-conscious).
#   - Full-text APPRAISAL + extraction: compliance-critical, long-document
#     reasoning, the result that carries citations into the CER -> Opus.
MODEL_SCREEN   = os.getenv("VIGIL_MODEL_SCREEN",   "claude-sonnet-4-6")
MODEL_EXTRACT  = os.getenv("VIGIL_MODEL_EXTRACT",  "claude-sonnet-4-6")
MODEL_APPRAISE = os.getenv("VIGIL_MODEL_APPRAISE", "claude-opus-4-8")
MODEL_DRAFT    = os.getenv("VIGIL_MODEL_DRAFT",    "claude-opus-4-8")

ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
MAX_TOKENS_SCREEN   = 1024
MAX_TOKENS_EXTRACT  = 4096
MAX_TOKENS_APPRAISE = 8192
MAX_TOKENS_DRAFT    = 8192

# Where the PRRC's uploaded full-text PDFs are stored (per run, per PMID).
UPLOADS_DIR = os.getenv("VIGIL_UPLOADS", "uploads")

# --- NCBI E-utilities ---------------------------------------------------------
# A free NCBI key raises the rate limit from 3 to 10 req/s. Optional but
# recommended. Get one at https://www.ncbi.nlm.nih.gov/account/settings/
NCBI_API_KEY = os.getenv("NCBI_API_KEY", "")
NCBI_EMAIL   = os.getenv("NCBI_EMAIL", "alejandro@vigil.example")
NCBI_TOOL    = "vigil-cer-assistant"
EUTILS_BASE  = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"
NCBI_RATE_DELAY = 0.34 if NCBI_API_KEY else 0.11

# --- Auto full-text retrieval (open access only) ------------------------------
# Tier 1: PMC open-access full text via NCBI.
# Tier 2: Unpaywall - legal open-access PDF by DOI.
# Tier 3: routed to the PRRC manual-upload list. Vigil never bypasses a paywall.
ENABLE_AUTO_RETRIEVAL = os.getenv("VIGIL_AUTO_RETRIEVAL", "1") == "1"
UNPAYWALL_BASE  = "https://api.unpaywall.org/v2"
UNPAYWALL_EMAIL = os.getenv("UNPAYWALL_EMAIL", NCBI_EMAIL)
RETRIEVAL_CACHE_DIR = os.getenv("VIGIL_RETRIEVAL_CACHE", "retrieval_cache")
MAX_PDF_BYTES = 25 * 1024 * 1024
HTTP_TIMEOUT = 45

# --- Run defaults -------------------------------------------------------------
DEFAULT_RETMAX_PER_TRACK = 30
PUBMED_SORT = os.getenv("VIGIL_PUBMED_SORT", "relevance")
DB_PATH = os.getenv("VIGIL_DB", "vigil.db")

# --- Prompt template versions (external, versioned) ---------------------------
PROMPT_SCREEN   = "prompts/screen_v1.txt"
PROMPT_EXTRACT  = "prompts/extract_v1.txt"
PROMPT_APPRAISE = "prompts/appraise_fulltext_v1.txt"
PROMPT_DRAFT    = "prompts/draft_section_v1.txt"
