"""Load artikelen.xlsx into Postgres: clean, build search_text, embed, bulk insert.

Run from the repo root:  python -m scripts.ingest
"""
import sys
import time
from pathlib import Path

import openpyxl

# Allow `python scripts/ingest.py` as well as `python -m scripts.ingest`.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import config          # noqa: E402
from app.db import connect      # noqa: E402
from app.embed import embed_passages  # noqa: E402
from app.normalize import normalize_text  # noqa: E402
from app.sizes import parse_size  # noqa: E402

BATCH = 1000
# Cap the text fed to the embedder. The model truncates near 128 tokens anyway,
# and norm/code/material/size all live in the first ~220 chars of search_text.
EMBED_CHARS = 220


def embed_texts(batch):
    return list(embed_passages((r["search_text"] or "")[:EMBED_CHARS] for r in batch))

# Map curated DB columns -> exact spreadsheet header names.
COLMAP = {
    "artikelcode": "ARTIKELCODE",
    "shortcode": "SHORTCODE",
    "norm": "NORM",
    "norm2": "NORM2",
    "en_norm": "EN-NORM",
    "materiaal": "MATERIAAL & OPPERVLAKTE",
    "materiaal_uitgebreid": "MATERIAAL UITGEBREID",
    "omschrijving": "OMSCHRIJVING",
    "winkelwagen_omschrijving": "WINKELWAGEN OMSCHRIJVING",
    "omschrijving_kort": "OMSCHRIJVING KORT",
    "maatvoering": "MAATVOERING",
    "variaties": "VARIATIES",
    "product_titel": "PRODUCT TITEL",
    "webshopmenu": "WEBSHOPMENU",
    "keuzemenu1": "KEUZEMENU1",
    "keuzemenu5": "KEUZEMENU5",
    "vpe": "VPE (VERPAKKINGSEENHEID) {number}",
    "afbeelding": "AFBEELDING UITGEBREID",
    "url_product": "URLP",
}
PRICE_HEADER = "PRIJS PER STUK {number}"

# Fields whose text carries norm / material / size / product signal for search.
SEARCH_FIELDS = [
    "norm", "norm2", "en_norm", "product_titel", "omschrijving",
    "winkelwagen_omschrijving", "omschrijving_kort", "materiaal",
    "materiaal_uitgebreid", "maatvoering", "variaties",
    "webshopmenu", "keuzemenu1", "keuzemenu5",
]

INSERT_COLS = list(COLMAP.keys()) + [
    "prijs_per_stuk", "raw", "search_text", "search_norm",
    "size_dia", "size_pitch", "size_len", "embedding",
]


def derive(rec):
    """Compute search_text + the derived recall columns (search_norm, size)."""
    rec["search_text"] = build_search_text(rec)
    rec["search_norm"] = normalize_text(rec["search_text"])
    s = parse_size(rec.get("maatvoering"))
    rec["size_dia"], rec["size_pitch"], rec["size_len"] = s.dia, s.pitch, s.length
    return rec


def clean(v):
    """Normalize a cell value to a clean string (or None)."""
    if v is None:
        return None
    s = str(v).replace("�", "€").strip()  # mojibake -> euro sign
    return s or None


def parse_price(v):
    s = clean(v)
    if not s:
        return None
    s = s.replace("€", "").replace(" ", "")
    # Heuristic: if both separators present, treat '.' as thousands, ',' as decimal.
    if "," in s and "." in s:
        s = s.replace(".", "").replace(",", ".")
    elif "," in s:
        s = s.replace(",", ".")
    keep = "".join(ch for ch in s if ch.isdigit() or ch in ".-")
    try:
        return float(keep) if keep not in ("", ".", "-") else None
    except ValueError:
        return None


def build_search_text(rec):
    seen, parts = set(), []
    for f in SEARCH_FIELDS:
        val = rec.get(f)
        if val and val not in seen:
            seen.add(val)
            parts.append(val)
    return " | ".join(parts)


def rows_from_xlsx(path=None):
    wb = openpyxl.load_workbook(path or config.ARTIKELEN_XLSX, read_only=True, data_only=True)
    ws = wb.worksheets[0]
    it = ws.iter_rows(values_only=True)
    header = [str(h).strip() if h is not None else "" for h in next(it)]
    idx = {name: i for i, name in enumerate(header)}
    missing = [h for h in list(COLMAP.values()) + [PRICE_HEADER] if h not in idx]
    if missing:
        raise SystemExit(f"Missing expected columns: {missing}")

    for raw_row in it:
        rec = {}
        for col, header_name in COLMAP.items():
            rec[col] = clean(raw_row[idx[header_name]])
        if not rec.get("artikelcode"):
            continue  # skip rows without a key
        rec["prijs_per_stuk"] = parse_price(raw_row[idx[PRICE_HEADER]])
        # Full raw record (all columns), cleaned for storage/debugging.
        rec["raw"] = {h: clean(raw_row[i]) for h, i in idx.items() if h}
        derive(rec)
        yield rec
    wb.close()


def insert_batch(cur, batch, vectors):
    """Fast bulk load via COPY (table is TRUNCATEd first, so no upsert)."""
    from psycopg.types.json import Jsonb
    from pgvector import Vector

    cols = ", ".join(INSERT_COLS)
    with cur.copy(f"COPY products ({cols}) FROM STDIN") as copy:
        for rec, vec in zip(batch, vectors):
            row = [rec.get(c) for c in COLMAP] + [
                rec["prijs_per_stuk"], Jsonb(rec["raw"]), rec["search_text"],
                rec["search_norm"], rec["size_dia"], rec["size_pitch"], rec["size_len"],
                Vector(vec),
            ]
            copy.write_row(row)


def main():
    t0 = time.time()
    print(f"Reading {config.ARTIKELEN_XLSX}")
    with connect() as conn:
        with conn.cursor() as cur:
            # Drop ANN index during bulk load, rebuild afterwards (much faster).
            cur.execute("DROP INDEX IF EXISTS products_embedding_hnsw")
            cur.execute("TRUNCATE products")
        conn.commit()

        total = 0
        batch = []
        for rec in rows_from_xlsx():
            batch.append(rec)
            if len(batch) >= BATCH:
                vectors = embed_texts(batch)
                with conn.cursor() as cur:
                    insert_batch(cur, batch, vectors)
                conn.commit()
                total += len(batch)
                print(f"  inserted {total:>7,}  ({(time.time()-t0):.0f}s)", flush=True)
                batch = []
        if batch:
            vectors = embed_texts(batch)
            with conn.cursor() as cur:
                insert_batch(cur, batch, vectors)
            conn.commit()
            total += len(batch)

        print(f"Building HNSW index over {total:,} rows ...", flush=True)
        with conn.cursor() as cur:
            cur.execute(
                "CREATE INDEX IF NOT EXISTS products_embedding_hnsw "
                "ON products USING hnsw (embedding vector_cosine_ops)"
            )
            cur.execute("ANALYZE products")
        conn.commit()
        print(f"Done: {total:,} products in {(time.time()-t0):.0f}s")


if __name__ == "__main__":
    main()
