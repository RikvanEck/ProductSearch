"""Populate products.search_norm (normalized text) and build its indexes.

Fast, embedding-free: reads search_text, applies app.normalize.normalize_text,
writes back via a temp table + UPDATE...FROM, then (re)creates trigram + FTS
indexes on the normalized column.

Run from repo root:  python -m scripts.normalize_index
"""
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.db import connect              # noqa: E402
from app.normalize import normalize_text  # noqa: E402


def main():
    t0 = time.time()
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute("ALTER TABLE products ADD COLUMN IF NOT EXISTS search_norm TEXT")
        conn.commit()

        print("Reading + normalizing search_text ...", flush=True)
        with conn.cursor() as cur:
            cur.execute("SELECT artikelcode, search_text FROM products")
            data = [(code, normalize_text(txt)) for code, txt in cur]
        print(f"  normalized {len(data):,}  ({time.time()-t0:.0f}s)", flush=True)

        # One transaction: temp table -> COPY -> UPDATE -> rebuild indexes.
        with conn.cursor() as cur:
            cur.execute("DROP INDEX IF EXISTS products_norm_trgm")
            cur.execute("DROP INDEX IF EXISTS products_norm_fts")
            cur.execute("CREATE TEMP TABLE _norm (artikelcode TEXT PRIMARY KEY, sn TEXT)")
            with cur.copy("COPY _norm (artikelcode, sn) FROM STDIN") as copy:
                for row in data:
                    copy.write_row(row)
            print("Updating products.search_norm ...", flush=True)
            cur.execute(
                "UPDATE products p SET search_norm = t.sn FROM _norm t "
                "WHERE p.artikelcode = t.artikelcode"
            )
            print("Building indexes on search_norm ...", flush=True)
            cur.execute(
                "CREATE INDEX products_norm_trgm ON products "
                "USING gin (search_norm gin_trgm_ops)"
            )
            cur.execute(
                "CREATE INDEX products_norm_fts ON products "
                "USING gin (to_tsvector('simple', coalesce(search_norm,'')))"
            )
        conn.commit()

        with conn.cursor() as cur:
            cur.execute("ANALYZE products")
        conn.commit()
    print(f"Done: normalized {len(data):,} rows in {time.time()-t0:.0f}s")


if __name__ == "__main__":
    main()
