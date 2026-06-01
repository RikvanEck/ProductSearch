"""foute_paren before/after report.

For every foute_paren row, grouped by its `Why Wrong` reason, measure:
  - in_pool : is the correct product (omschrijving == col D) in the retrieved pool, where?
              (Groq-free; isolates retrieval recall.)
  - correct@1 / correct@3 : after rerank, is col D the top-1 / in top-3? (needs Groq)

Usage (from repo root):
  python -m scripts.foute_report --save before.json        # baseline (with rerank)
  python -m scripts.foute_report --no-rerank               # recall only, fast
  python -m scripts.foute_report --compare before.json     # print before->after deltas
"""
import argparse
import json
import re
import sys
from pathlib import Path

import openpyxl

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import config              # noqa: E402
from app.rerank import rerank       # noqa: E402
from app.retrieve import retrieve   # noqa: E402


def norm(s: str) -> str:
    return re.sub(r"\s+", "", (s or "").upper())


def category(why: str) -> str:
    w = (why or "").lower()
    parts = []
    if "norm" in w:
        parts.append("norm")
    if "materiaal" in w or "materaal" in w:
        parts.append("materiaal")
    if "maat" in w:
        parts.append("maat")
    return "+".join(parts) if parts else "other"


def load_cases():
    wb = openpyxl.load_workbook(config.FOUTE_PAREN_XLSX, read_only=True, data_only=True)
    ws = wb["voorbeelden"]
    cases = []
    for r in ws.iter_rows(min_row=2, values_only=True):
        if r[0] and r[3]:
            cases.append({
                "query": str(r[0]).strip(),
                "why": str(r[2]).strip() if r[2] else "",
                "right": str(r[3]).strip(),
            })
    wb.close()
    return cases


def evaluate(cases, use_rerank: bool):
    results = []
    for i, c in enumerate(cases, 1):
        target = norm(c["right"])
        pool = retrieve(c["query"])
        pos = next((j for j, p in enumerate(pool)
                    if norm(p.get("omschrijving")) == target), None)
        rec = {
            "query": c["query"], "right": c["right"], "why": c["why"],
            "category": category(c["why"]),
            "in_pool": pos is not None, "pos": pos,
            "correct1": None, "correct3": None,
        }
        if use_rerank:
            rr = rerank(c["query"], pool[: config.RERANK_INPUT])
            order = rr["order"][:3]
            descs = [norm(next((p.get("omschrijving") for p in pool
                                if p["artikelcode"] == code), "")) for code in order]
            rec["correct1"] = bool(descs[:1] == [target])
            rec["correct3"] = target in descs
        results.append(rec)
        print(f"  {i}/{len(cases)}  in_pool={rec['in_pool']}  pos={rec['pos']}"
              f"  c@1={rec['correct1']}  [{rec['category']}]", flush=True)
    return results


def summarize(results, use_rerank):
    cats = {}
    for r in results:
        for key in (r["category"], "TOTAL"):
            d = cats.setdefault(key, {"n": 0, "in_pool": 0, "c1": 0, "c3": 0})
            d["n"] += 1
            d["in_pool"] += int(r["in_pool"])
            d["c1"] += int(bool(r["correct1"]))
            d["c3"] += int(bool(r["correct3"]))
    # "ANY size" aggregate across all categories mentioning maat.
    size = [r for r in results if "maat" in r["category"]]
    if size:
        cats["ANY-size(maat)"] = {
            "n": len(size),
            "in_pool": sum(r["in_pool"] for r in size),
            "c1": sum(bool(r["correct1"]) for r in size),
            "c3": sum(bool(r["correct3"]) for r in size),
        }
    return cats


def print_table(cats, baseline=None, use_rerank=True):
    hdr = f"{'category':<18}{'n':>4}{'in_pool':>10}"
    if use_rerank:
        hdr += f"{'correct@1':>11}{'correct@3':>11}"
    print(hdr)
    print("-" * len(hdr))
    order = sorted(cats, key=lambda k: (k == "TOTAL", k == "ANY-size(maat)", k))
    for k in order:
        d = cats[k]
        def cell(cur_key, base_key):
            cur = d[cur_key]
            s = f"{cur}/{d['n']}"
            if baseline and k in baseline:
                delta = cur - baseline[k][cur_key]
                s += f" ({'+' if delta >= 0 else ''}{delta})"
            return s
        row = f"{k:<18}{d['n']:>4}{cell('in_pool','in_pool'):>10}"
        if use_rerank:
            row += f"{cell('c1','c1'):>11}{cell('c3','c3'):>11}"
        print(row)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-rerank", action="store_true")
    ap.add_argument("--save", metavar="FILE")
    ap.add_argument("--compare", metavar="FILE")
    args = ap.parse_args()
    use_rerank = not args.no_rerank

    cases = load_cases()
    print(f"foute_paren cases: {len(cases)}  rerank={use_rerank}\n")
    results = evaluate(cases, use_rerank)
    cats = summarize(results, use_rerank)

    baseline = None
    if args.compare and Path(args.compare).exists():
        baseline = json.loads(Path(args.compare).read_text())

    print("\n=== foute_paren report ===")
    print_table(cats, baseline=baseline, use_rerank=use_rerank)

    if args.save:
        Path(args.save).write_text(json.dumps(cats, indent=2))
        print(f"\nsaved baseline -> {args.save}")


if __name__ == "__main__":
    main()
