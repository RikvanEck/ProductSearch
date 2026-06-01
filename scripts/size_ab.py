"""A/B: effect of the exact-size retrieval pass on foute_paren recall.

Robust metric: map each 'Right Result' (col D) to catalog artikelcodes by normalized
omschrijving, then check whether any maps into the retrieved pool. Toggle the size pass
with SIZE_BOOST so ON vs OFF is comparable. Groq-free.

  SIZE_BOOST=0 python -m scripts.size_ab   # baseline (no size pass)
  SIZE_BOOST=1 python -m scripts.size_ab   # with size pass
"""
import re
import sys
from pathlib import Path

import openpyxl

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import config              # noqa: E402
from app.db import connect          # noqa: E402
from app.retrieve import retrieve   # noqa: E402


def norm(s):
    return re.sub(r"\s+", "", (s or "").upper())


def cat(w):
    w = (w or "").lower()
    p = [x for x, k in [("norm", "norm"), ("mat", "materiaal"), ("maat", "maat")] if k in w]
    return "+".join(p) or "other"


def main():
    wb = openpyxl.load_workbook(config.FOUTE_PAREN_XLSX, read_only=True, data_only=True)
    ws = wb["voorbeelden"]
    cases = [(str(r[0]).strip(), str(r[2]).strip() if r[2] else "", str(r[3]).strip())
             for r in ws.iter_rows(min_row=2, values_only=True) if r[0] and r[3]]
    wb.close()

    agg = {}
    with connect() as conn, conn.cursor() as cur:
        for q, why, right in cases:
            cur.execute(
                "SELECT artikelcode FROM products "
                "WHERE replace(upper(omschrijving),' ','') = %s", (norm(right),))
            codes = {r[0] for r in cur.fetchall()}
            pool = {p["artikelcode"] for p in retrieve(q)}
            k = cat(why)
            d = agg.setdefault(k, [0, 0, 0])  # total, mappable, in_pool
            d[0] += 1
            if codes:
                d[1] += 1
                if codes & pool:
                    d[2] += 1

    print(f"SIZE_BOOST={config.SIZE_BOOST}")
    print(f"{'category':<10}{'total':>6}{'mappable':>10}{'in_pool':>9}")
    tot = [0, 0, 0]
    for k in sorted(agg):
        d = agg[k]
        print(f"{k:<10}{d[0]:>6}{d[1]:>10}{d[2]:>9}")
        tot = [tot[i] + d[i] for i in range(3)]
    print(f"{'TOTAL':<10}{tot[0]:>6}{tot[1]:>10}{tot[2]:>9}")


if __name__ == "__main__":
    main()
