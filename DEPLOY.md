# Deploying to GitHub + Railway

This app runs as two Railway services: a **Postgres+pgvector** database and the
**FastAPI app** (built from the `Dockerfile`). You load data once by **dumping your
already-embedded local database and restoring it to Railway** — no slow re-ingest.

## 0. Prerequisites
- Local Docker Postgres is running and loaded (`docker compose up -d` + ingest already done).
- A GitHub account and a Railway account.
- Your `GROQ_API_KEY` (the one in `.env` — consider rotating it since it was shared in chat).

## 1. Push the code to GitHub
`.env` and caches are gitignored, so no secrets are pushed.
```bash
cd webshop-search
git init
git add .
git commit -m "Ferrofast AI product search"
git branch -M main
git remote add origin https://github.com/<you>/ferrofast-search.git
git push -u origin main
```

## 2. Create the database service (Postgres + pgvector)
Railway's default Postgres lacks the `vector` extension, so deploy the pgvector image:
1. New Project → **Deploy from Docker Image** → `pgvector/pgvector:pg16`.
2. Add a **Volume** mounted at `/var/lib/postgresql/data`.
3. Set service **Variables**: `POSTGRES_USER=ferrofast`, `POSTGRES_PASSWORD=<pick-one>`,
   `POSTGRES_DB=ferrofast`.
4. Note the connection string. Internal (for the app): `DATABASE_URL` of this service.
   Public (for restoring from your laptop): enable a TCP proxy → gives a host:port.

## 3. Deploy the app service
1. New service → **Deploy from GitHub repo** → pick the repo. Railway detects the
   `Dockerfile` (model is baked in, so no cold-start download).
2. Set the app service **Variables**:
   - `GROQ_API_KEY=<your key>`
   - `GROQ_MODEL=llama-3.1-8b-instant`
   - `EMBED_MODEL=sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2`
   - `DATABASE_URL=${{Postgres.DATABASE_URL}}` (reference the DB service; use its internal URL)
3. Networking → **Generate Domain**.

## 4. Load data: dump locally, restore to Railway (no re-embedding)
Your local DB already has the schema, extensions, 129k embedded rows, and indexes.
`pg_dump` includes all of it (incl. `CREATE EXTENSION vector`).

```bash
# Dump from the local Docker Postgres (custom format)
docker exec ferrofast_pg pg_dump -U ferrofast -d ferrofast -Fc -f /tmp/ferrofast.dump
docker cp ferrofast_pg:/tmp/ferrofast.dump ./ferrofast.dump

# Restore into Railway (use the PUBLIC connection URL from step 2).
# Run the client from the matching pg16 image so versions line up:
docker run --rm -v "${PWD}:/work" pgvector/pgvector:pg16 \
  pg_restore --no-owner --no-acl --clean --if-exists \
  -d "postgresql://ferrofast:<pwd>@<public-host>:<port>/ferrofast" /work/ferrofast.dump
```
- PowerShell: replace `${PWD}` with `${PWD}` works in PowerShell too, or use an absolute path.
- The restore rebuilds the HNSW index (a few minutes, one-time).
- Verify: `SELECT count(*) FROM products;` should be 129009.

## 5. Verify the live app
Open the generated domain → run a `foute_paren` query → confirm results + AI reasoning.
If the reranker shows a 429, the free Groq tier is throttling; it falls back to retrieval
order and retries with backoff.

## 6. Ongoing product changes (no full re-index)
Run the incremental tools against the cloud DB (set `DATABASE_URL` to the public URL, or use
`railway run` so the service env is injected):
```bash
railway run python -m scripts.upsert --file changes.xlsx      # add/update changed rows only
railway run python -m scripts.upsert --delete <code> <code>   # remove products
```
Only changed rows are re-embedded (seconds); HNSW updates incrementally. Wire this into your
catalog-export pipeline (e.g. a nightly job that exports the day's changed/removed SKUs).

## Notes
- **Resources**: the app uses ~300–500 MB RAM (onnxruntime). DB storage for 129k rows +
  384-dim vectors is ~200–300 MB.
- **Secrets**: never commit `.env`; manage keys as Railway variables. Rotate the Groq key.
- **Model**: baked into the image at build, so deploys/restarts don't re-download it.
- **Alternative data load**: you *can* run `python -m scripts.ingest` against the cloud DB
  instead, but it re-embeds all 129k rows (~80+ min) and needs the 32 MB xlsx uploaded —
  dump/restore is strongly preferred.
