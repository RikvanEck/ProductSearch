"""Hybrid candidate retrieval: vector KNN + full-text + trigram word similarity."""
import re
from typing import Dict, List

from . import config
from .db import connect
from .embed import embed_query
from .normalize import normalize_text
from .sizes import parse_size

_STOP = {"DE", "HET", "EN", "VAN", "MET", "MM", "PER", "THE", "AND", "FOR"}
# A norm/article code: a short letter prefix followed by >=2 digits (ISO4762, D912, A28530).
_CODE = re.compile(r"^[A-Z]{1,4}\d{2,}$")


_NON_ALNUM = re.compile(r"[^A-Z0-9]")


def _tokens(norm_query: str) -> List[str]:
    """Alphanumeric tokens worth matching (length >= 2 or pure digits).

    Tokens are stripped to [A-Z0-9] so they are always valid `to_tsquery`
    lexemes (characters like ! & | : * would otherwise be parsed as operators).
    """
    out = []
    for raw in norm_query.split():
        t = _NON_ALNUM.sub("", raw)
        if not t or t in _STOP:
            continue
        if len(t) >= 2 or t.isdigit():
            out.append(t)
    return out


def _codes(tokens: List[str]) -> List[str]:
    return [t for t in tokens if _CODE.match(t)]

# Columns returned to the rest of the pipeline / UI.
DISPLAY_COLS = [
    "artikelcode", "shortcode", "norm", "norm2", "en_norm", "materiaal",
    "materiaal_uitgebreid", "omschrijving", "winkelwagen_omschrijving",
    "omschrijving_kort", "maatvoering", "variaties", "product_titel",
    "webshopmenu", "keuzemenu1", "keuzemenu5", "prijs_per_stuk", "vpe",
    "afbeelding", "url_product",
]
_COLS_SQL = ", ".join(DISPLAY_COLS)
# Also pull the combined "size, packing unit & price" text (column AE) from raw.
_VERPAKKING_KEY = "MAATVOERING & VERPAKKINGSEENHEID"
_SELECT_SQL = _COLS_SQL + f", raw->>'{_VERPAKKING_KEY}' AS verpakkingseenheid"


def _rowdict(row) -> Dict:
    d = dict(zip(DISPLAY_COLS, row[: len(DISPLAY_COLS)]))
    if d.get("prijs_per_stuk") is not None:
        d["prijs_per_stuk"] = float(d["prijs_per_stuk"])
    d["verpakkingseenheid"] = row[len(DISPLAY_COLS)] if len(row) > len(DISPLAY_COLS) else None
    return d


def retrieve(query: str) -> List[Dict]:
    """Return up to CANDIDATE_LIMIT candidate products, recall-ordered.

    Combines three signals; each contributes a rank-based score in [0,1] and we
    sum them. The LLM reranker makes the final precise decision, so this only
    needs good recall.
    """
    qvec = embed_query(query)
    qn = normalize_text(query)  # DIN->D, size separators -> spaces, etc.
    qsize = parse_size(query)   # diameter / pitch / length from the query
    scores: Dict[str, float] = {}
    records: Dict[str, Dict] = {}

    def add(source_rows, weight: float = 1.0):
        n = len(source_rows)
        for rank, row in enumerate(source_rows):
            rec = _rowdict(row)
            code = rec["artikelcode"]
            records.setdefault(code, rec)
            scores[code] = scores.get(code, 0.0) + weight * (n - rank) / n  # 1.0 .. ~0

    with connect() as conn, conn.cursor() as cur:
        # 1) Vector KNN (cosine).
        cur.execute(
            f"SELECT {_SELECT_SQL} FROM products "
            "ORDER BY embedding <=> %s::vector LIMIT %s",
            (qvec, config.VECTOR_TOPK),
        )
        add(cur.fetchall())

        def guarded(sql, params, weight: float = 1.0):
            """Run an optional retrieval pass; never let one query break the rest."""
            try:
                cur.execute(sql, params)
                add(cur.fetchall(), weight=weight)
            except Exception:  # noqa: BLE001
                conn.rollback()

        # 2) Full-text over the NORMALIZED text, OR-combined and ranked.
        #    OR (not AND) so sharing the norm code + size still surfaces an item
        #    even when the English query words are absent from the Dutch catalog.
        toks = _tokens(qn)
        if toks:
            guarded(
                f"SELECT {_SELECT_SQL} FROM products, "
                "to_tsquery('simple', %s) q "
                "WHERE to_tsvector('simple', coalesce(search_norm,'')) @@ q "
                "ORDER BY ts_rank_cd(to_tsvector('simple', coalesce(search_norm,'')), q) "
                "DESC LIMIT %s",
                (" | ".join(toks), config.KEYWORD_TOPK),
            )

        # 3) Trigram word similarity on the normalized text (fuzzy / typo tolerant).
        guarded(
            f"SELECT {_SELECT_SQL} FROM products "
            "WHERE %s <%% search_norm "
            "ORDER BY word_similarity(%s, search_norm) DESC LIMIT %s",
            (qn, qn, config.KEYWORD_TOPK),
        )

        # 4) Norm-code family boost: among products sharing the query's norm code,
        #    rank by overall normalized similarity (brings the right size into pool).
        codes = _codes(toks)
        if codes:
            guarded(
                f"SELECT {_SELECT_SQL} FROM products, to_tsquery('simple', %s) q "
                "WHERE to_tsvector('simple', coalesce(search_norm,'')) @@ q "
                "ORDER BY word_similarity(%s, search_norm) DESC LIMIT %s",
                (" | ".join(codes), qn, config.KEYWORD_TOPK),
            )

        # 5) Exact-size boost (slot-aware): products whose diameter (and length / pitch
        #    when the query gives them) match. When the query also has a norm code, AND
        #    it in — otherwise huge size families (e.g. 5000+ M20 parts) bury the right
        #    item below the limit.
        #
        #    Weight is specificity-aware: a full size (diameter + length, e.g. M6x20) is a
        #    strong, precise signal and must DOMINATE ranking so the correct size beats
        #    wrong-size items that merely share tokens like "20"/"70". A bare diameter
        #    (e.g. "M20") is weak/ambiguous, so it only nudges.
        if config.SIZE_BOOST and qsize.dia is not None:
            specific = qsize.length is not None or qsize.pitch is not None
            # Cast nullable params to numeric so Postgres can type a bare NULL
            # (e.g. when the query gives no pitch) instead of erroring.
            size_where = (
                "WHERE size_dia = %s::numeric "
                "AND (%s::numeric IS NULL OR size_len = %s::numeric) "
                "AND (%s::numeric IS NULL OR size_pitch = %s::numeric) "
            )
            size_params = [qsize.dia, qsize.length, qsize.length, qsize.pitch, qsize.pitch]
            if codes:
                size_where += (
                    "AND to_tsvector('simple', coalesce(search_norm,'')) "
                    "@@ to_tsquery('simple', %s) "
                )
                size_params.append(" | ".join(codes))
            guarded(
                f"SELECT {_SELECT_SQL} FROM products " + size_where +
                "ORDER BY word_similarity(%s, search_norm) DESC LIMIT %s",
                tuple(size_params + [qn, config.KEYWORD_TOPK]),
                weight=8.0 if specific else 2.0,
            )

    ranked = sorted(records.values(), key=lambda r: -scores[r["artikelcode"]])
    return ranked[: config.CANDIDATE_LIMIT]
