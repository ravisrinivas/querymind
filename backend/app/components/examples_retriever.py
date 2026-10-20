"""Component 4 — Examples Retriever: top-k similar (question → SQL) pairs via ChromaDB (numpy fallback)."""
from __future__ import annotations

import threading
import uuid
from typing import Optional

import numpy as np

from ..llm.embeddings import Embedder, get_embedder
from ..schemas import Example, RetrieverResult
from ..store import AdminStore

try:  # pragma: no cover - import guard
    import chromadb
except Exception:  # pragma: no cover
    chromadb = None


class ExamplesRetriever:
    def __init__(self, store: AdminStore, embedder: Optional[Embedder] = None, use_chroma: bool = True):
        self.store = store
        self.embedder = embedder or get_embedder()
        self._lock = threading.RLock()
        self._use_chroma = bool(use_chroma and chromadb is not None)
        self._client = chromadb.EphemeralClient() if self._use_chroma else None
        self._collection = None
        self._np_ids: list[int] = []
        self._np_vecs = np.zeros((0, self.embedder.dim), dtype=np.float32)
        self._np_meta: dict[int, dict] = {}
        self.reindex()

    @property
    def backend(self) -> str:
        return "chromadb" if self._use_chroma else "numpy"

    # ── indexing ──
    def reindex(self) -> int:
        """Rebuild the index from the Examples Manager table. Called after every example add/edit/delete."""
        rows = self.store.list_examples()
        if hasattr(self.embedder, "fit"):
            self.embedder.fit([r["question"] for r in rows])
        with self._lock:
            vecs = self.embedder.embed([r["question"] for r in rows]) if rows else np.zeros((0, self.embedder.dim))
            if self._use_chroma:
                if self._collection is not None:
                    try:
                        self._client.delete_collection(self._collection.name)
                    except Exception:
                        pass
                self._collection = self._client.create_collection(
                    name=f"ex_{uuid.uuid4().hex[:12]}", metadata={"hnsw:space": "cosine"}, embedding_function=None)
                if rows:
                    self._collection.add(
                        ids=[str(r["id"]) for r in rows], embeddings=vecs.tolist(),
                        documents=[r["question"] for r in rows],
                        metadatas=[{"sql": r["sql"], "query_type": r["query_type"] or ""} for r in rows])
            else:
                self._np_ids = [r["id"] for r in rows]
                self._np_vecs = np.asarray(vecs, dtype=np.float32)
                self._np_meta = {r["id"]: r for r in rows}
        return len(rows)

    # ── retrieval ──
    def retrieve(self, question: str, k: int = 4, query_type: Optional[str] = None) -> RetrieverResult:
        with self._lock:
            n = len(self._collection.get()["ids"]) if self._use_chroma else len(self._np_ids)
            if n == 0:
                return RetrieverResult(examples=[])
            q = self.embedder.embed([question])
            k = max(1, min(k, n))
            if self._use_chroma:
                res = self._collection.query(query_embeddings=q.tolist(), n_results=k)
                exs = [Example(id=int(i), question=d, sql=m["sql"], query_type=m.get("query_type") or None,
                               score=round(1 - float(dist), 4))
                       for i, d, m, dist in zip(res["ids"][0], res["documents"][0], res["metadatas"][0],
                                                res["distances"][0])]
            else:
                sims = self._np_vecs @ q[0]
                order = np.argsort(-sims)[:k]
                exs = [Example(id=self._np_ids[i], question=self._np_meta[self._np_ids[i]]["question"],
                               sql=self._np_meta[self._np_ids[i]]["sql"],
                               query_type=self._np_meta[self._np_ids[i]]["query_type"], score=round(float(sims[i]), 4))
                       for i in order]
        return RetrieverResult(examples=exs)

    def search(self, query: str, k: int = 5) -> list[Example]:
        return self.retrieve(query, k=k).examples
