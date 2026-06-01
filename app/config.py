"""Central configuration loaded from environment / .env."""
import os
from pathlib import Path

from dotenv import load_dotenv

# Repo root = parent of the app/ package.
ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")

GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")
# 8b-instant has much higher free-tier rate limits (TPM) and handles the
# norm/material/size discrimination well. Switch to llama-3.3-70b-versatile for
# slightly stronger reasoning if your Groq tier allows the token throughput.
GROQ_MODEL = os.getenv("GROQ_MODEL", "llama-3.1-8b-instant")

DATABASE_URL = os.getenv(
    "DATABASE_URL", "postgresql://ferrofast:ferrofast@localhost:5432/ferrofast"
)

EMBED_MODEL = os.getenv(
    "EMBED_MODEL", "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
)
EMBED_DIM = 384


def _resolve(p: str) -> str:
    """Resolve a possibly-relative data path against the repo root."""
    path = Path(p)
    return str(path if path.is_absolute() else (ROOT / path).resolve())


ARTIKELEN_XLSX = _resolve(os.getenv("ARTIKELEN_XLSX", "../artikelen.xlsx"))
JUISTE_PAREN_XLSX = _resolve(os.getenv("JUISTE_PAREN_XLSX", "../juiste_paren.xlsx"))
FOUTE_PAREN_XLSX = _resolve(
    os.getenv("FOUTE_PAREN_XLSX", "../foute_paren_voorbeelden.xlsx")
)

# Retrieval tuning
VECTOR_TOPK = int(os.getenv("VECTOR_TOPK", "60"))
KEYWORD_TOPK = int(os.getenv("KEYWORD_TOPK", "80"))
CANDIDATE_LIMIT = int(os.getenv("CANDIDATE_LIMIT", "80"))
RERANK_INPUT = int(os.getenv("RERANK_INPUT", "60"))  # max candidates sent to the LLM
RERANK_RETURN = int(os.getenv("RERANK_RETURN", "5"))
SIZE_BOOST = os.getenv("SIZE_BOOST", "1").lower() not in ("0", "false", "no")
