"""FastAPI app: search UI + JSON search endpoint."""
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from .db import connect
from .search import search

STATIC = Path(__file__).resolve().parent / "static"
app = FastAPI(title="Ferrofast AI Product Search")


class SearchRequest(BaseModel):
    query: str
    use_rerank: bool = True
    limit: int = 5


@app.get("/")
def index():
    return FileResponse(STATIC / "index.html")


@app.post("/search")
def do_search(req: SearchRequest):
    q = (req.query or "").strip()
    if not q:
        raise HTTPException(400, "Empty query")
    return search(q, use_rerank=req.use_rerank, limit=req.limit)


@app.get("/product/{code}")
def product(code: str):
    """Return the full raw product record (all catalog columns)."""
    with connect() as conn, conn.cursor() as cur:
        cur.execute("SELECT raw FROM products WHERE artikelcode = %s", (code,))
        row = cur.fetchone()
    if not row:
        raise HTTPException(404, "Not found")
    raw = row[0] or {}
    # Drop empty values so the details view stays readable.
    return {"artikelcode": code, "fields": {k: v for k, v in raw.items() if v not in (None, "")}}


app.mount("/static", StaticFiles(directory=STATIC), name="static")
