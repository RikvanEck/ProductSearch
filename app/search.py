"""Orchestrate: retrieve candidates -> (optional) LLM rerank -> assemble results."""
from typing import Dict, List

from . import config
from .rerank import rerank
from .retrieve import retrieve


def search(query: str, use_rerank: bool = True, limit: int = None) -> Dict:
    limit = limit or config.RERANK_RETURN
    candidates = retrieve(query)
    by_code = {c["artikelcode"]: c for c in candidates}

    if use_rerank:
        rr = rerank(query, candidates[: config.RERANK_INPUT])
        order, reasons, best_reason = rr["order"], rr["reasons"], rr["best_reason"]
    else:
        order = [c["artikelcode"] for c in candidates]
        reasons, best_reason = {}, "Keyword/vector retrieval only (rerank disabled)."

    results: List[Dict] = []
    for code in order[:limit]:
        rec = dict(by_code[code])
        rec["match_reason"] = reasons.get(code, "")
        results.append(rec)

    return {
        "query": query,
        "best_reason": best_reason,
        "candidate_count": len(candidates),
        "results": results,
    }
