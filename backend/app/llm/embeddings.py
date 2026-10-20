"""Embedding backends for few-shot retrieval.

Default: a deterministic, dependency-free hashing embedder (word + bigram + character-trigram features,
sublinear TF, L2-normalised). It needs no model download so the system runs offline; swap in
sentence-transformers by setting EMBEDDING_BACKEND=sbert (and `pip install sentence-transformers`).
"""
from __future__ import annotations

import hashlib
import os
import re
from typing import Protocol

import numpy as np

_STOP = {"the", "a", "an", "of", "for", "to", "in", "on", "is", "are", "was", "were", "me", "show", "list", "give",
         "please", "what", "which", "who", "how", "do", "does", "did", "we", "our", "us", "all", "and", "with", "by"}


def lemma(w: str) -> str:
    if len(w) > 4 and w.endswith("ies"):
        return w[:-3] + "y"
    if len(w) > 4 and w.endswith("sses"):
        return w[:-2]
    if len(w) > 3 and w.endswith("s") and not w.endswith(("ss", "us", "is")):
        return w[:-1]
    return w


def tokenize(text: str) -> list[str]:
    return [lemma(t) for t in re.findall(r"[a-z0-9_]+", text.lower())]


class Embedder(Protocol):
    name: str
    dim: int
    def embed(self, texts: list[str]) -> np.ndarray: ...


class HashEmbedder:
    name = "hash-512"

    def __init__(self, dim: int = 512):
        self.dim = dim
        self._idf: dict[str, float] = {}
        self._max_idf = 1.0

    def fit(self, texts: list[str]) -> None:
        """Learn inverse-document-frequency weights from the example corpus so rare, informative words
        ("cheapest", "refunded") outweigh words that appear in every question ("product", "customer")."""
        import math
        df: dict[str, int] = {}
        for t in texts:
            for w in set(tokenize(t)):
                df[w] = df.get(w, 0) + 1
        n = max(len(texts), 1)
        self._idf = {w: math.log((n + 1) / (c + 1)) + 1.0 for w, c in df.items()}
        self._max_idf = math.log(n + 1) + 1.0

    def _w(self, token: str) -> float:
        return self._idf.get(token, self._max_idf if self._idf else 1.0)

    def _h(self, feat: str) -> int:
        return int(hashlib.md5(feat.encode()).hexdigest()[:8], 16)

    def embed(self, texts: list[str]) -> np.ndarray:
        out = np.zeros((len(texts), self.dim), dtype=np.float32)
        for i, t in enumerate(texts):
            toks = [w for w in tokenize(t) if w not in _STOP] or tokenize(t)
            feats = [f"w:{w}" for w in toks] + [f"b:{a}_{b}" for a, b in zip(toks, toks[1:])]
            for w in toks:
                padded = f"#{w}#"
                feats += [f"c:{padded[j:j + 3]}" for j in range(len(padded) - 2)]
            for f in feats:
                h = self._h(f)
                base = f.split(":", 1)[1].replace("_", " ").split(" ")[0] if f[0] in "wb" else f[2:]
                weight = (2.0 if f[0] == "w" else 1.0) * (self._w(base) if f[0] == "w" else 1.0)
                out[i, h % self.dim] += (1.0 if (h >> 20) & 1 else -1.0) * weight
            n = np.linalg.norm(out[i])
            if n:
                out[i] /= n
        return out


class SbertEmbedder:  # optional
    def __init__(self, model: str = "sentence-transformers/all-MiniLM-L6-v2"):
        from sentence_transformers import SentenceTransformer
        self._m = SentenceTransformer(model)
        self.name, self.dim = model, self._m.get_sentence_embedding_dimension()

    def embed(self, texts: list[str]) -> np.ndarray:
        return np.asarray(self._m.encode(texts, normalize_embeddings=True), dtype=np.float32)


def get_embedder() -> Embedder:
    if os.getenv("EMBEDDING_BACKEND", "hash") == "sbert":
        try:
            return SbertEmbedder()
        except Exception as e:  # pragma: no cover
            print(f"[embeddings] sbert unavailable ({e}); falling back to hash embedder")
    return HashEmbedder()
