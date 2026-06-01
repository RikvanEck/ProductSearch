-- Ferrofast product search schema
CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS pg_trgm;

CREATE TABLE IF NOT EXISTS products (
    artikelcode             TEXT PRIMARY KEY,
    shortcode               TEXT,
    norm                    TEXT,
    norm2                   TEXT,
    en_norm                 TEXT,
    materiaal               TEXT,   -- MATERIAAL & OPPERVLAKTE
    materiaal_uitgebreid    TEXT,
    omschrijving            TEXT,
    winkelwagen_omschrijving TEXT,
    omschrijving_kort       TEXT,
    maatvoering             TEXT,
    variaties               TEXT,
    product_titel           TEXT,
    webshopmenu             TEXT,
    keuzemenu1              TEXT,
    keuzemenu5              TEXT,
    prijs_per_stuk          NUMERIC,
    vpe                     TEXT,
    afbeelding              TEXT,
    url_product             TEXT,
    raw                     JSONB,
    search_text             TEXT,
    search_norm             TEXT,   -- normalized text for keyword/trigram recall
    size_dia                NUMERIC, -- parsed from maatvoering (diameter)
    size_pitch              NUMERIC, -- thread pitch (fine threads only)
    size_len                NUMERIC, -- length
    embedding               vector(384)
);

-- Keyword / fuzzy
CREATE INDEX IF NOT EXISTS products_search_trgm
    ON products USING gin (search_text gin_trgm_ops);

-- Full-text (language-agnostic 'simple' config: NL + EN technical tokens)
CREATE INDEX IF NOT EXISTS products_search_fts
    ON products USING gin (to_tsvector('simple', coalesce(search_text, '')));

-- Vector ANN (cosine). Built after load in ingest for speed, but safe to create here.
CREATE INDEX IF NOT EXISTS products_embedding_hnsw
    ON products USING hnsw (embedding vector_cosine_ops);

-- Normalized keyword/trigram + structured size (populated by scripts/normalize_index.py
-- and scripts/size_index.py; see those for details).
CREATE INDEX IF NOT EXISTS products_norm_trgm
    ON products USING gin (search_norm gin_trgm_ops);
CREATE INDEX IF NOT EXISTS products_norm_fts
    ON products USING gin (to_tsvector('simple', coalesce(search_norm, '')));
CREATE INDEX IF NOT EXISTS products_size_idx
    ON products (size_dia, size_len);
