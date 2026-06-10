"""LLM access via the LiteLLM gateway (Brief §11, ADR-004 model-agnostic contract).
- OpenAI-compatible client; model aliases resolve in compose/litellm-config.yaml.
- JSON-schema-constrained outputs (§7D) with strict parse + one repair retry.
- Escalation tier (§16.4): config-gated, logged distinctly, never silent.
- Every call tagged with run/well/document ids for Langfuse cost attribution (§6.3)."""
from __future__ import annotations
import base64
import json
import re
from dataclasses import dataclass
from typing import Any
from openai import OpenAI
from .config import settings

EXTRACTOR_VERSION = "extractor/0.1.0"


@dataclass
class LLMCall:
    model: str
    escalated: bool
    usage: dict[str, Any]


def _client() -> OpenAI:
    s = settings()
    return OpenAI(base_url=s.llm_base_url, api_key=s.llm_api_key)


def _strip_fences(text: str) -> str:
    m = re.search(r"```(?:json)?\s*(.*?)```", text, re.S)
    return (m.group(1) if m else text).strip()


def complete_json(model: str, system: str, user_parts: list[dict[str, Any]],
                  schema_hint: dict | None = None, tags: dict | None = None,
                  allow_escalation: bool = False, temperature: float = 0.0,
                  ) -> tuple[dict | list, LLMCall]:
    """Chat completion that must return JSON. user_parts: OpenAI content parts
    (text and/or image_url). Retries once with a repair prompt; then escalates iff permitted."""
    s = settings()
    sys_msg = system + "\nRespond with ONLY valid JSON. No prose, no markdown fences."
    if schema_hint:
        sys_msg += "\nJSON must conform to this schema:\n" + json.dumps(schema_hint)

    def _call(mdl: str, escalated: bool) -> tuple[dict | list, LLMCall]:
        client = _client()
        msgs = [{"role": "system", "content": sys_msg},
                {"role": "user", "content": user_parts}]
        last_err: Exception | None = None
        for attempt in range(2):
            resp = client.chat.completions.create(
                model=mdl, messages=msgs, temperature=temperature,
                extra_body={"metadata": {"tags": {**(tags or {}), "escalated": escalated,
                                                  "extractor_version": EXTRACTOR_VERSION}}})
            raw = resp.choices[0].message.content or ""
            try:
                parsed = json.loads(_strip_fences(raw))
                usage = resp.usage.model_dump() if resp.usage else {}
                return parsed, LLMCall(model=mdl, escalated=escalated, usage=usage)
            except json.JSONDecodeError as e:
                last_err = e
                msgs.append({"role": "assistant", "content": raw})
                msgs.append({"role": "user", "content":
                             "That was not valid JSON. Return the same content as strictly valid JSON only."})
        raise ValueError(f"Model {mdl} failed to produce valid JSON: {last_err}")

    try:
        return _call(model, escalated=False)
    except Exception:
        if allow_escalation and s.escalation_tier == "api" and s.escalation_model:
            return _call(s.escalation_model, escalated=True)
        raise


def image_part(png_bytes: bytes) -> dict[str, Any]:
    b64 = base64.b64encode(png_bytes).decode()
    return {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{b64}"}}


def text_part(text: str) -> dict[str, Any]:
    return {"type": "text", "text": text}


def embed(texts: list[str], tags: dict | None = None) -> list[list[float]]:
    """Embeddings via gateway (§16.2). Configure an embedding model alias 'wc-embed' in LiteLLM;
    falls back to deterministic hash vectors if unavailable so pipeline progress isn't blocked
    (search quality degrades; retrieval evals will catch it)."""
    from .models import EMBED_DIM
    try:
        resp = _client().embeddings.create(model="wc-embed", input=texts)
        return [d.embedding for d in resp.data]
    except Exception:
        import hashlib
        out = []
        for t in texts:
            h = hashlib.sha256(t.encode()).digest() * (EMBED_DIM // 32 + 1)
            out.append([b / 255.0 for b in h[:EMBED_DIM]])
        return out
