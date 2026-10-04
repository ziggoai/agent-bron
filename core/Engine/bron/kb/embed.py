"""The meaning model: turns text into vectors so search can find passages by sense, not just by word."""
from __future__ import annotations

from pathlib import Path

import numpy as np

from ..vault import Vault
from .store import KbError, kb_dir

MODEL = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
DIM = 384


class Embedder:
    """Loads the model on first use (the first run downloads about 220 MB into `cache`)."""

    def __init__(self, cache: Path):
        self.cache = Path(cache)
        self._model = None
        self.model = MODEL

    def _load(self):
        if self._model is None:
            try:
                from fastembed import TextEmbedding

                self.cache.mkdir(parents=True, exist_ok=True)
                self._model = TextEmbedding(MODEL, cache_dir=str(self.cache))
            except Exception as exc:  # download, disk or install problems
                reason = (str(exc).splitlines() or [type(exc).__name__])[0][:80] or type(exc).__name__
                raise KbError(f"The meaning-search model couldn't be loaded ({reason}). Keyword search still works.") from exc
        return self._model

    def embed(self, texts: list[str]) -> np.ndarray:
        if not texts:
            return np.zeros((0, DIM), dtype=np.float32)
        model = self._load()
        rows = np.asarray(list(model.embed(list(texts))), dtype=np.float32)
        norms = np.linalg.norm(rows, axis=1, keepdims=True)
        return rows / np.where(norms == 0, 1, norms)


_CACHE: dict[Path, Embedder] = {}


def get(vault: Vault) -> Embedder:
    cache = kb_dir(vault) / "models"
    if cache not in _CACHE:
        _CACHE[cache] = Embedder(cache)
    return _CACHE[cache]
