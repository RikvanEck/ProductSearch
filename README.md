# Ferrofast — AI Product Search

Search ~129k Ferrofast products with free-text queries. A query is matched by
**hybrid retrieval** (local embeddings + Postgres keyword/trigram) and then
**reranked by a Groq LLM** that is shown each candidate's norm / material / size,
so it avoids the wrong-norm / wrong-material / wrong-size mistakes.

## Stack
- **PostgreSQL 16 + pgvector** (Docker) — product catalog + vector + text indexes
- **fastembed** (`paraphrase-multilingual-MiniLM-L12-v2`, 384-dim) — free local embeddings, no API key
- **Groq** (`llama-3.3-70b-versatile`) — LLM reranker
- **FastAPI** + vanilla HTML/JS frontend

## Setup

```bash
cd webshop-search

# 1. Start Postgres (creates schema on first boot)
docker compose up -d

# 2. Python deps
python -m pip install -r requirements.txt

# 3. Configure: copy and add your Groq key
cp .env.example .env          # Windows: copy .env.example .env
#  -> edit .env, set GROQ_API_KEY=...

# 4. Load the catalog (reads ../artikelen.xlsx, embeds, inserts ~129k rows)
python -m scripts.ingest

# 5. Run the web app
uvicorn app.main:app --reload
#  -> open http://localhost:8000
```

## Evaluate accuracy

```bash
python -m scripts.evaluate --n 300              # full pipeline (retrieval + Groq rerank)
python -m scripts.evaluate --n 300 --no-rerank  # retrieval-only baseline (isolates the LLM's value)
```

- **juiste_paren**: accuracy@1 / @3 vs the labeled `Artikelcode_Ferrofast`
  (labels whose code isn't in the catalog are skipped and counted).
- **foute_paren**: how many of the 62 known hard cases now return the correct product.

## Updating products (no full re-index)
The ~80-min run is a one-time bulk load. Ongoing changes touch only the changed rows
(embedding is per-row; pgvector's HNSW index updates incrementally):
```bash
python -m scripts.upsert --file changes.xlsx       # add/update changed rows (artikelen.xlsx layout)
python -m scripts.upsert --delete <code> <code>    # delete products
```
`scripts/ingest.py` now also populates the derived columns (`search_norm`, `size_*`), so a
fresh load is a single command. `scripts/normalize_index.py` and `scripts/size_index.py`
remain available to recompute those columns in bulk if the logic changes.

## Deploy
See `DEPLOY.md` for GitHub + Railway (Docker image with the model baked in, pgvector DB,
and dump/restore of the already-embedded database — no cloud re-ingest).

## Layout
```
docker-compose.yml  Dockerfile  railway.json  db/schema.sql  requirements.txt  .env.example
app/   config.py db.py embed.py normalize.py sizes.py retrieve.py rerank.py search.py main.py  static/index.html
scripts/  ingest.py  upsert.py  normalize_index.py  size_index.py  evaluate.py  foute_report.py  size_ab.py
```

## Tuning (env vars, all optional)
`GROQ_MODEL`, `EMBED_MODEL`, `VECTOR_TOPK`, `KEYWORD_TOPK`, `CANDIDATE_LIMIT`,
`RERANK_INPUT`, `RERANK_RETURN`, `SIZE_BOOST` (set `0` to disable the exact-size pass).

## Notes
- First `ingest` run downloads the ONNX embedding model (one-time, free).
- Groq model availability changes over time; override with `GROQ_MODEL` in `.env`.
  Default `llama-3.1-8b-instant` (high free-tier limits); `llama-3.3-70b-versatile`
  reasons a bit better if your tier allows the throughput.
- The reranker degrades gracefully (with 429 backoff) to retrieval order if Groq is throttled/unavailable.
