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


def _strip_fences(text: str) -> str:
    t = text.strip()
    if t.startswith("```"):
        # drop first fence line and trailing fence
        t = t.split("\n", 1)[1] if "\n" in t else t
        if t.rstrip().endswith("```"):
            t = t.rstrip()[:-3]
    return t.strip()


def call_text(model: str, system: str, user: str, max_tokens: int) -> str:
    """Call Claude and return raw text (used for Markdown drafting)."""
    if _client is None:
        raise RuntimeError(
            "Anthropic client not configured. Set ANTHROPIC_API_KEY and "
            "`pip install anthropic`. (Offline tests should mock this function.)"
        )
    resp = _client.messages.create(
        model=model,
        max_tokens=max_tokens,
        system=system,
        messages=[{"role": "user", "content": user}],
    )
    return "".join(b.text for b in resp.content if getattr(b, "type", None) == "text")


def call_json(model: str, system: str, user: str, max_tokens: int) -> dict:
    """Call Claude, expect a single JSON object, parse it. Fails safe."""
    if _client is None:
        raise RuntimeError(
            "Anthropic client not configured. Set ANTHROPIC_API_KEY and "
            "`pip install anthropic`. (Offline tests should mock this function.)"
        )
    resp = _client.messages.create(
        model=model,
        max_tokens=max_tokens,
        system=system,
        messages=[{"role": "user", "content": user}],
    )
    text = "".join(b.text for b in resp.content if getattr(b, "type", None) == "text")
    try:
        return json.loads(_strip_fences(text))
    except json.JSONDecodeError:
        # Under-claim on failure rather than guess.
        return {"_parse_error": True, "raw": text[:2000]}


def call_json_pdf(model: str, system: str, user: str, pdf_bytes: bytes,
                  max_tokens: int) -> dict:
    """Call Claude with a PDF sent NATIVELY as a document block (preserves tables
    and layout - where adverse-event/performance data lives). Expects JSON back.

    Used for full-text appraisal. Fails safe to a parse-error object.
    """
    if _client is None:
        raise RuntimeError(
            "Anthropic client not configured. Set ANTHROPIC_API_KEY and "
            "`pip install anthropic`. (Offline tests should mock this function.)"
        )
    b64 = base64.standard_b64encode(pdf_bytes).decode("utf-8")
    resp = _client.messages.create(
        model=model,
        max_tokens=max_tokens,
        system=system,
        messages=[{
            "role": "user",
            "content": [
                {"type": "document",
                 "source": {"type": "base64",
                            "media_type": "application/pdf",
                            "data": b64}},
                {"type": "text", "text": user},
            ],
        }],
    )
    text = "".join(b.text for b in resp.content if getattr(b, "type", None) == "text")
    try:
        return json.loads(_strip_fences(text))
    except json.JSONDecodeError:
        return {"_parse_error": True, "raw": text[:2000]}


def call_json_fulltext_text(model: str, system: str, user: str, fulltext: str,
                            max_tokens: int) -> dict:
    """Appraise full text supplied as PLAIN TEXT / XML-flattened (e.g. PMC open
    access). The article body is embedded in the user message. Expects JSON back.
    Fails safe to a parse-error object."""
    if _client is None:
        raise RuntimeError(
            "Anthropic client not configured. Set ANTHROPIC_API_KEY and "
            "`pip install anthropic`. (Offline tests should mock this function.)"
        )
    composed = f"{user}\n\n--- FULL TEXT (open access) ---\n{fulltext}"
    resp = _client.messages.create(
        model=model, max_tokens=max_tokens, system=system,
        messages=[{"role": "user", "content": composed}],
    )
    text = "".join(b.text for b in resp.content if getattr(b, "type", None) == "text")
    try:
        return json.loads(_strip_fences(text))
    except json.JSONDecodeError:
        return {"_parse_error": True, "raw": text[:2000]}
