"""Incremental index maintenance — add / update / delete a FEW products.

Production updates do NOT require re-embedding the whole catalog. Only the changed
rows are embedded (seconds), and pgvector's HNSW index updates incrementally on
insert/update. Deletes are a plain DELETE (no embedding, no rebuild).

Usage (from repo root):
  # add or update the products in a small xlsx (same column layout as artikelen.xlsx)
  python -m scripts.upsert --file changes.xlsx

  # delete by artikelcode(s)
  python -m scripts.upsert --delete 912001301080065 285303400200300
  python -m scripts.upsert --delete-file removed_codes.txt   # one code per line
"""
import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.db import connect              # noqa: E402
from app.embed import embed_passages    # noqa: E402
from scripts.ingest import (            # noqa: E402  (reuse cleaning/derive/columns)
    COLMAP, INSERT_COLS, EMBED_CHARS, rows_from_xlsx,
)

# Update every column on conflict except the primary key.
_UPDATE_SET = ", ".join(f"{c}=EXCLUDED.{c}" for c in INSERT_COLS if c != "artikelcode")
_PLACEHOLDERS = "(" + ", ".join(["%s"] * len(INSERT_COLS)) + ")"
_SQL = (
    f"INSERT INTO products ({', '.join(INSERT_COLS)}) VALUES {_PLACEHOLDERS} "
    f"ON CONFLICT (artikelcode) DO UPDATE SET {_UPDATE_SET}"
)


def upsert_file(path: str, batch_size: int = 200) -> int:
    from psycopg.types.json import Jsonb
    from pgvector import Vector

    t0 = time.time()
    total = 0
    with connect() as conn:
        batch = []

        def flush(rows):
            nonlocal total
            if not rows:
                return
            vecs = list(embed_passages((r["search_text"] or "")[:EMBED_CHARS] for r in rows))
            params = []
            for rec, vec in zip(rows, vecs):
                params.append([rec.get(c) for c in COLMAP] + [
                    rec["prijs_per_stuk"], Jsonb(rec["raw"]), rec["search_text"],
                    rec["search_norm"], rec["size_dia"], rec["size_pitch"],
                    rec["size_len"], Vector(vec),
                ])
            with conn.cursor() as cur:
                cur.executemany(_SQL, params)
            conn.commit()
            total += len(rows)

        for rec in rows_from_xlsx(path):
            batch.append(rec)
            if len(batch) >= batch_size:
                flush(batch)
                batch = []
        flush(batch)
    print(f"Upserted {total} products in {time.time()-t0:.1f}s")
    return total


def delete_codes(codes) -> int:
    codes = [c for c in codes if c]
    if not codes:
        return 0
    with connect() as conn, conn.cursor() as cur:
        cur.execute("DELETE FROM products WHERE artikelcode = ANY(%s)", (codes,))
        n = cur.rowcount
        conn.commit()
    print(f"Deleted {n} products")
    return n


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--file", help="xlsx of rows to add/update (artikelen.xlsx layout)")
    ap.add_argument("--delete", nargs="*", default=[], help="artikelcodes to delete")
    ap.add_argument("--delete-file", help="file with one artikelcode per line to delete")
    args = ap.parse_args()

    if args.file:
        upsert_file(args.file)
    codes = list(args.delete)
    if args.delete_file:
        codes += [ln.strip() for ln in Path(args.delete_file).read_text().splitlines()]
    if codes:
        delete_codes(codes)
    if not args.file and not codes:
        ap.error("nothing to do: pass --file and/or --delete/--delete-file")


if __name__ == "__main__":
    main()
