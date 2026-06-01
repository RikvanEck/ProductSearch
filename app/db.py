"""Postgres connection helpers (psycopg 3 + pgvector)."""
from contextlib import contextmanager

import psycopg
from pgvector.psycopg import register_vector

from . import config


@contextmanager
def connect():
    """Yield a single connection with pgvector types registered."""
    conn = psycopg.connect(config.DATABASE_URL)
    try:
        register_vector(conn)
        yield conn
    finally:
        conn.close()
