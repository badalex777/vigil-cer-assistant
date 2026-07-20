"""
Vigil - Anthropic LLM wrapper.

Guardrail enforcement at the call level (Pipeline Spec ?2.2, guardrail 4):
  - Structured JSON output only.
  - Prompts are EXTERNAL and versioned (loaded from prompts/), never hardcoded.
  - "If unknown, say unknown" is instructed in every prompt template.
  - The wrapper defaults to under-claiming: on parse failure it returns an
    explicit error object rather than fabricating a result.

Requires: pip install anthropic
"""
from __future__ import annotations
import json
import base64
import functools

import config

try:
    import anthropic
    _client = anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY) if config.ANTHROPIC_API_KEY else None
except ImportError:  # allow import without the SDK installed (for offline tests)
    anthropic = None
    _client = None


@functools.lru_cache(maxsize=8)
def load_prompt(path: str) -> str:
    with open(path) as f:
        return f.read()


def split_stable_variable(tmpl: str, marker: str) -> tuple[str, str]:
    """Split a loaded prompt template into a stable (cacheable) prefix and a
    variable suffix, at the first occurrence of `marker` (the marker itself
    stays in the variable half). Used to build Anthropic prompt-caching
    breakpoints without touching prompt wording - the template file is read
    unmodified; only how it's sliced into blocks changes.

    Raises ValueError if `marker` is not found, so a future prompt edit that
    removes the marker fails loudly instead of silently caching nothing."""
    idx = tmpl.index(marker)
    return tmpl[:idx], tmpl[idx:]


def _strip_fences(text: str) -> str:
    t = text.strip()
    if t.startswith("```"):
        # drop first fence line and trailing fence
        t = t.split("\n", 1)[1] if "\n" in t else t
        if t.rstrip().endswith("```"):
            t = t.rstrip()[:-3]
    return t.strip()


def _cacheable_blocks(stable: str, variable: str) -> list[dict]:
    """Build a user-content block list with a cache_control breakpoint at the
    end of the stable prefix. `stable` must be byte-identical across every
    call meant to share this cache entry; `variable` is the per-call
    remainder and is never cached. If the prefix is shorter than the model's
    minimum cacheable length, the breakpoint is a harmless no-op (the API
    just doesn't cache it - no error, no extra cost)."""
    blocks = []
    if stable:
        blocks.append({"type": "text", "text": stable,
                       "cache_control": {"type": "ephemeral"}})
    blocks.append({"type": "text", "text": variable})
    return blocks


def call_text(model: str, system: str, user_stable: str, user_variable: str,
              max_tokens: int) -> str:
    """Call Claude and return raw text (used for Markdown drafting).

    user_stable: the cacheable prefix (identical across calls that share it).
    user_variable: the per-call remainder, sent uncached after it."""
    if _client is None:
        raise RuntimeError(
            "Anthropic client not configured. Set ANTHROPIC_API_KEY and "
            "`pip install anthropic`. (Offline tests should mock this function.)"
        )
    resp = _client.messages.create(
        model=model,
        max_tokens=max_tokens,
        system=system,
        messages=[{"role": "user", "content": _cacheable_blocks(user_stable, user_variable)}],
    )
    return "".join(b.text for b in resp.content if getattr(b, "type", None) == "text")


def call_json(model: str, system: str, user_stable: str, user_variable: str,
             max_tokens: int) -> dict:
    """Call Claude, expect a single JSON object, parse it. Fails safe.

    user_stable: the cacheable prefix (identical across calls that share it).
    user_variable: the per-call remainder, sent uncached after it."""
    if _client is None:
        raise RuntimeError(
            "Anthropic client not configured. Set ANTHROPIC_API_KEY and "
            "`pip install anthropic`. (Offline tests should mock this function.)"
        )
    resp = _client.messages.create(
        model=model,
        max_tokens=max_tokens,
        system=system,
        messages=[{"role": "user", "content": _cacheable_blocks(user_stable, user_variable)}],
    )
    text = "".join(b.text for b in resp.content if getattr(b, "type", None) == "text")
    try:
        return json.loads(_strip_fences(text))
    except json.JSONDecodeError:
        # Under-claim on failure rather than guess.
        return {"_parse_error": True, "raw": text[:2000]}


def call_json_pdf(model: str, system: str, user_stable: str, user_variable: str,
                  pdf_bytes: bytes, max_tokens: int) -> dict:
    """Call Claude with a PDF sent NATIVELY as a document block (preserves tables
    and layout - where adverse-event/performance data lives). Expects JSON back.

    user_stable: the cacheable prefix, sent BEFORE the PDF so it stays a valid
    cache prefix (the PDF itself is unique per paper and is never cached).
    user_variable: the per-paper remainder, sent after the PDF.

    Used for full-text appraisal. Fails safe to a parse-error object.
    """
    if _client is None:
        raise RuntimeError(
            "Anthropic client not configured. Set ANTHROPIC_API_KEY and "
            "`pip install anthropic`. (Offline tests should mock this function.)"
        )
    b64 = base64.standard_b64encode(pdf_bytes).decode("utf-8")
    content = []
    if user_stable:
        content.append({"type": "text", "text": user_stable,
                        "cache_control": {"type": "ephemeral"}})
    content.append({"type": "document",
                    "source": {"type": "base64",
                               "media_type": "application/pdf",
                               "data": b64}})
    content.append({"type": "text", "text": user_variable})
    resp = _client.with_options(max_retries=config.APPRAISE_MAX_RETRIES).messages.create(
        model=model,
        max_tokens=max_tokens,
        system=system,
        messages=[{"role": "user", "content": content}],
        timeout=config.APPRAISE_TIMEOUT_S,
    )
    text = "".join(b.text for b in resp.content if getattr(b, "type", None) == "text")
    try:
        return json.loads(_strip_fences(text))
    except json.JSONDecodeError:
        return {"_parse_error": True, "raw": text[:2000]}


def call_json_fulltext_text(model: str, system: str, user_stable: str, user_variable: str,
                            fulltext: str, max_tokens: int) -> dict:
    """Appraise full text supplied as PLAIN TEXT / XML-flattened (e.g. PMC open
    access). The article body is embedded after user_variable, so it never
    enters the cached prefix (it's unique per paper). Expects JSON back.
    Fails safe to a parse-error object."""
    if _client is None:
        raise RuntimeError(
            "Anthropic client not configured. Set ANTHROPIC_API_KEY and "
            "`pip install anthropic`. (Offline tests should mock this function.)"
        )
    composed_variable = f"{user_variable}\n\n--- FULL TEXT (open access) ---\n{fulltext}"
    resp = _client.with_options(max_retries=config.APPRAISE_MAX_RETRIES).messages.create(
        model=model, max_tokens=max_tokens, system=system,
        messages=[{"role": "user", "content": _cacheable_blocks(user_stable, composed_variable)}],
        timeout=config.APPRAISE_TIMEOUT_S,
    )
    text = "".join(b.text for b in resp.content if getattr(b, "type", None) == "text")
    try:
        return json.loads(_strip_fences(text))
    except json.JSONDecodeError:
        return {"_parse_error": True, "raw": text[:2000]}
