"""Populate products.size_dia / size_pitch / size_len from `maatvoering`.

Fast and embedding-free (parse + temp table + UPDATE...FROM + btree index),
mirroring scripts/normalize_index.py.

Run from repo root:  python -m scripts.size_index
"""
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.db import connect          # noqa: E402
from app.sizes import parse_size    # noqa: E402


def main():
    t0 = time.time()
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "ALTER TABLE products "
                "ADD COLUMN IF NOT EXISTS size_dia NUMERIC, "
                "ADD COLUMN IF NOT EXISTS size_pitch NUMERIC, "
                "ADD COLUMN IF NOT EXISTS size_len NUMERIC"
            )
        conn.commit()

        print("Parsing maatvoering -> size signature ...", flush=True)
        with conn.cursor() as cur:
            cur.execute("SELECT artikelcode, maatvoering FROM products")
            rows = []
            for code, maat in cur:
                s = parse_size(maat)
                rows.append((code, s.dia, s.pitch, s.length))
        parsed = sum(1 for r in rows if r[1] is not None)
        print(f"  parsed dia for {parsed:,}/{len(rows):,}  ({time.time()-t0:.0f}s)", flush=True)

        with conn.cursor() as cur:
            cur.execute("DROP INDEX IF EXISTS products_size_idx")
            cur.execute(
                "CREATE TEMP TABLE _sz (artikelcode TEXT PRIMARY KEY, "
                "dia NUMERIC, pitch NUMERIC, len NUMERIC)"
            )
            with cur.copy("COPY _sz (artikelcode, dia, pitch, len) FROM STDIN") as copy:
                for row in rows:
                    copy.write_row(row)
            print("Updating size columns ...", flush=True)
            cur.execute(
                "UPDATE products p SET size_dia = t.dia, size_pitch = t.pitch, "
                "size_len = t.len FROM _sz t WHERE p.artikelcode = t.artikelcode"
            )
            print("Building index (size_dia, size_len) ...", flush=True)
            cur.execute(
                "CREATE INDEX products_size_idx ON products (size_dia, size_len)"
            )
        conn.commit()

        with conn.cursor() as cur:
            cur.execute("ANALYZE products")
        conn.commit()
    print(f"Done: {len(rows):,} rows in {time.time()-t0:.0f}s")


if __name__ == "__main__":
    main()
