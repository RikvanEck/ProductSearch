"""Accuracy evaluation.

  juiste_paren.xlsx  : query=Omschrijving_Relatie, expected numeric Artikelcode_Ferrofast.
                       Scored accuracy@1 / @3 (codes absent from the catalog are skipped).
  foute_paren        : query=Search Query, expected omschrijving = 'Right Result' (col D).
                       Scored as: did a top-K result's omschrijving match the expected one.

Run from repo root:
  python -m scripts.evaluate --n 300            # full pipeline
  python -m scripts.evaluate --n 300 --no-rerank  # retrieval-only baseline
"""
import argparse
import random
import re
import sys
from pathlib import Path

import openpyxl

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import config              # noqa: E402
from app.db import connect          # noqa: E402
from app.search import search       # noqa: E402


def norm(s: str) -> str:
    return re.sub(r"\s+", "", (s or "").upper())


def catalog_codes(codes):
    """Return the subset of codes that exist in the products table."""
    codes = [c for c in codes if c]
    if not codes:
        return set()
    with connect() as conn, conn.cursor() as cur:
        cur.execute("SELECT artikelcode FROM products WHERE artikelcode = ANY(%s)", (codes,))
        return {r[0] for r in cur.fetchall()}


def eval_juiste(n, use_rerank, seed, topk=3):
    wb = openpyxl.load_workbook(config.JUISTE_PAREN_XLSX, read_only=True, data_only=True)
    ws = wb["Blad1"]
    it = ws.iter_rows(min_row=2, values_only=True)
    rows = [(str(r[0]).strip(), str(r[3]).strip()) for r in it if r[0] and r[3]]
    wb.close()

    random.seed(seed)
    sample = random.sample(rows, min(n, len(rows)))
    present = catalog_codes([code for _, code in sample])
    usable = [(q, c) for q, c in sample if c in present]
    skipped = len(sample) - len(usable)

    hit1 = hit3 = 0
    print(f"\n== juiste_paren ==  sampled={len(sample)} usable={len(usable)} "
          f"skipped(not in catalog)={skipped}  rerank={use_rerank}")
    for i, (query, expected) in enumerate(usable, 1):
        res = search(query, use_rerank=use_rerank, limit=topk)
        codes = [r["artikelcode"] for r in res["results"]]
        if codes[:1] == [expected]:
            hit1 += 1
        if expected in codes[:topk]:
            hit3 += 1
        if i % 25 == 0:
            print(f"  {i}/{len(usable)}  acc@1={hit1/i:.1%}  acc@{topk}={hit3/i:.1%}", flush=True)
    d = max(len(usable), 1)
    print(f"  RESULT  acc@1={hit1/d:.1%}  acc@{topk}={hit3/d:.1%}  (n={len(usable)})")
    return hit1, hit3, len(usable)


def eval_foute(use_rerank, topk=3):
    wb = openpyxl.load_workbook(config.FOUTE_PAREN_XLSX, read_only=True, data_only=True)
    ws = wb["voorbeelden"]
    cases = [(str(r[0]).strip(), str(r[3]).strip())
             for r in ws.iter_rows(min_row=2, values_only=True) if r[0] and r[3]]
    wb.close()

    hit1 = hit3 = 0
    print(f"\n== foute_paren (hard cases) ==  cases={len(cases)}  rerank={use_rerank}")
    for query, expected in cases:
        res = search(query, use_rerank=use_rerank, limit=topk)
        descs = [norm(r.get("omschrijving")) for r in res["results"]]
        descs_ww = [norm(r.get("winkelwagen_omschrijving")) for r in res["results"]]
        exp = norm(expected)
        top = [descs[0], descs_ww[0]] if res["results"] else []
        if exp in top:
            hit1 += 1
        if exp in descs[:topk] or exp in descs_ww[:topk]:
            hit3 += 1
    d = max(len(cases), 1)
    print(f"  RESULT  correct@1={hit1/d:.1%}  correct@{topk}={hit3/d:.1%}  (n={len(cases)})")
    return hit1, hit3, len(cases)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=300, help="juiste_paren sample size")
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--no-rerank", action="store_true", help="retrieval-only baseline")
    ap.add_argument("--skip-juiste", action="store_true")
    ap.add_argument("--skip-foute", action="store_true")
    args = ap.parse_args()
    use_rerank = not args.no_rerank

    if not args.skip_juiste:
        eval_juiste(args.n, use_rerank, args.seed)
    if not args.skip_foute:
        eval_foute(use_rerank)


if __name__ == "__main__":
    main()
