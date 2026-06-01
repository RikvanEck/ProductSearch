"""Rerank retrieved candidates with a Groq LLM.

The model is shown each candidate's norm / material / size / description and must
pick the best matches WITHOUT substituting a different norm, material, or size --
these are exactly the mistakes seen in foute_paren_voorbeelden.xlsx.
"""
import json
import time
from functools import lru_cache
from typing import Dict, List

from groq import Groq

from . import config

SYSTEM = """You are a precise product matcher for a fastener/hardware webshop.
Given a customer SEARCH QUERY and a numbered list of CANDIDATE products, pick the
candidates that best match the query.

Hard rules:
- The NORM/standard must match (e.g. ISO4762 / DIN912). Never substitute a different norm.
- The MATERIAL and surface/strength must match (e.g. RVS-A2 vs RVS-A4, ST/U vs ST/S). Never substitute a different material.
- The SIZE/dimensions must match EXACTLY: diameter AND length AND (if given) thread pitch
  (e.g. M12x1.5x16 != M12x1.25x16 and != M16x1.5x16). Never substitute a near size.
- If several candidates are equally valid, rank the closest first.
- Only choose from the given candidates. Use their exact 'artikelcode'.

Respond ONLY with JSON of the form:
{"ranked": [{"artikelcode": "<code>", "reason": "<short why>"}], "best_reason": "<one sentence>"}
List at most %d candidates, best first. If nothing matches well, return the closest and say so.
""" % config.RERANK_RETURN


@lru_cache(maxsize=1)
def _client() -> Groq:
    if not config.GROQ_API_KEY:
        raise RuntimeError("GROQ_API_KEY is not set (add it to .env).")
    return Groq(api_key=config.GROQ_API_KEY)


def _create_with_retry(messages, max_attempts: int = 5):
    """Call Groq, backing off on 429 rate limits (free tier is strict)."""
    delay = 3.0
    last = None
    for attempt in range(max_attempts):
        try:
            return _client().chat.completions.create(
                model=config.GROQ_MODEL,
                temperature=0,
                response_format={"type": "json_object"},
                messages=messages,
            )
        except Exception as e:  # noqa: BLE001
            last = e
            status = getattr(e, "status_code", None)
            retry_after = None
            try:
                retry_after = float(getattr(e, "response", None).headers.get("retry-after"))
            except Exception:  # noqa: BLE001
                pass
            if status == 429 and attempt < max_attempts - 1:
                time.sleep(retry_after if retry_after else delay)
                delay = min(delay * 2, 30)
                continue
            raise
    raise last


def _fmt(cands: List[Dict]) -> str:
    lines = []
    for i, c in enumerate(cands, 1):
        norm = " / ".join(x for x in [c.get("norm"), c.get("en_norm"), c.get("norm2")] if x)
        size = " ".join(x for x in [c.get("maatvoering"), c.get("variaties")] if x)
        desc = (c.get("product_titel") or c.get("omschrijving")
                or c.get("winkelwagen_omschrijving") or "")[:60]
        lines.append(
            f"{i}. artikelcode={c['artikelcode']} | norm={norm or '-'} | "
            f"material={c.get('materiaal') or '-'} | size={size or '-'} | desc={desc}"
        )
    return "\n".join(lines)


def rerank(query: str, candidates: List[Dict]) -> Dict:
    """Return {"order": [artikelcodes], "reasons": {code: why}, "best_reason": str}.

    Falls back to recall order if the LLM output can't be used.
    """
    if not candidates:
        return {"order": [], "reasons": {}, "best_reason": "No candidates found."}

    valid = {c["artikelcode"] for c in candidates}
    fallback = [c["artikelcode"] for c in candidates[: config.RERANK_RETURN]]
    try:
        resp = _create_with_retry(
            messages=[
                {"role": "system", "content": SYSTEM},
                {"role": "user", "content": f"SEARCH QUERY:\n{query}\n\nCANDIDATES:\n{_fmt(candidates)}"},
            ],
        )
        data = json.loads(resp.choices[0].message.content)
        ranked = data.get("ranked", []) or []
        order, reasons = [], {}
        for item in ranked:
            code = str(item.get("artikelcode", "")).strip()
            if code in valid and code not in order:
                order.append(code)
                reasons[code] = item.get("reason", "")
        if not order:
            return {"order": fallback, "reasons": {}, "best_reason": "LLM returned no usable match; showing top retrieval results."}
        return {"order": order, "reasons": reasons, "best_reason": data.get("best_reason", "")}
    except Exception as e:  # noqa: BLE001 - degrade gracefully to recall order
        return {"order": fallback, "reasons": {}, "best_reason": f"Rerank unavailable ({e}); showing top retrieval results."}
