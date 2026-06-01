"""Local, free embeddings via fastembed (ONNX), 384-dim multilingual (NL + EN).

Default model: sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2.
e5-family models expect "query: ..." / "passage: ..." instruction prefixes; other
models do not. We add the prefixes only for e5 models so index-time and query-time
encoding stay consistent either way.
"""
from functools import lru_cache
from typing import Iterable, Iterator, List

from fastembed import TextEmbedding

from . import config

_IS_E5 = "e5" in config.EMBED_MODEL.lower()


@lru_cache(maxsize=1)
def _model() -> TextEmbedding:
    return TextEmbedding(model_name=config.EMBED_MODEL)


def embed_passages(texts: Iterable[str], batch_size: int = 256) -> Iterator[List[float]]:
    """Yield embeddings for documents. Streams to keep memory low."""
    if _IS_E5:
        texts = (f"passage: {t or ''}" for t in texts)
    else:
        texts = (t or "" for t in texts)
    for vec in _model().embed(texts, batch_size=batch_size):
        yield vec.tolist()


def embed_query(text: str) -> List[float]:
    """Embed a single search query."""
    text = f"query: {text or ''}" if _IS_E5 else (text or "")
    return next(_model().embed([text])).tolist()
