"""Lazy, persistent BAAI/bge-m3 query-embedding service (spec_v004 §4).

Loaded on first use and kept in memory for the life of the process — never
reloaded per request, never used for corpus vectorization (that pipeline is
`bim_rag.stage2_embed`, untouched by this module). Every encode call is
batch size one (a single query string), applying the same conservative
device/thread controls established after the Task 03 CUDA stability
incident (`bim_rag.config.THREAD_LIMIT`, `torch.inference_mode()`, explicit
CUDA synchronize, no automatic retry after a device error) —
reimplemented here rather than reaching into `bim_rag.stage2_embed`'s
private (`_`-prefixed) helpers across a package boundary.

A query vector returned by `embed_query()` is a plain Python list, never
written anywhere — there is no database write path in this module at all.
"""

from __future__ import annotations

import threading
from enum import Enum
from functools import lru_cache

from query.rag.errors import EmbeddingServiceUnavailableError

EMBEDDING_MODEL_NAME = "BAAI/bge-m3"
EMBEDDING_DIM = 1024


class EmbeddingServiceState(str, Enum):
    NOT_LOADED = "not_loaded"
    LOADING = "loading"
    READY = "ready"
    FAILED = "failed"


def _detect_device() -> tuple["object", str]:
    import torch

    if torch.cuda.is_available():
        return torch.device("cuda"), f"CUDA ({torch.cuda.get_device_name(0)})"
    return torch.device("cpu"), "CPU (CUDA unavailable)"


class EmbeddingService:
    """One instance is the process-wide singleton (`get_embedding_service()`).

    Additional instances with a deliberately-bad `model_name` are how tests
    exercise degraded-mode behavior without touching the real singleton.
    """

    def __init__(self, model_name: str = EMBEDDING_MODEL_NAME) -> None:
        self._model_name = model_name
        self._model = None
        self._state = EmbeddingServiceState.NOT_LOADED
        self._device_str: str | None = None
        self._load_error: str | None = None
        self._lock = threading.Lock()

    @property
    def state(self) -> EmbeddingServiceState:
        return self._state

    @property
    def device_str(self) -> str | None:
        return self._device_str

    @property
    def model_name(self) -> str:
        return self._model_name

    def ensure_loaded(self) -> None:
        """Idempotent. Raises EmbeddingServiceUnavailableError on failure —
        this process does not retry a failed load (spec_v004 §4)."""
        if self._state is EmbeddingServiceState.READY:
            return
        with self._lock:
            if self._state is EmbeddingServiceState.READY:
                return
            if self._state is EmbeddingServiceState.FAILED:
                raise EmbeddingServiceUnavailableError(
                    f"embedding service previously failed to load: {self._load_error}"
                )
            self._state = EmbeddingServiceState.LOADING
            try:
                import torch
                from sentence_transformers import SentenceTransformer

                from bim_rag.config import THREAD_LIMIT

                torch.set_num_threads(THREAD_LIMIT)
                device, device_str = _detect_device()
                self._model = SentenceTransformer(self._model_name, device=str(device))
                self._device_str = device_str
                self._state = EmbeddingServiceState.READY
            except Exception as exc:
                self._state = EmbeddingServiceState.FAILED
                self._load_error = str(exc)
                raise EmbeddingServiceUnavailableError(
                    f"embedding service failed to load {self._model_name!r}: {exc}"
                ) from exc

    def embed_query(self, text: str) -> list[float]:
        """Encode exactly one query string (batch size one). Never persisted."""
        self.ensure_loaded()
        import torch

        try:
            with torch.inference_mode():
                vector = self._model.encode(
                    [text],
                    batch_size=1,
                    show_progress_bar=False,
                    convert_to_numpy=True,
                    normalize_embeddings=True,
                )
            if self._model.device.type == "cuda":
                torch.cuda.synchronize()
        except Exception as exc:
            raise EmbeddingServiceUnavailableError(
                f"query embedding failed: {exc}. Stopping — no automatic retry after a "
                "device-stability failure."
            ) from exc

        result = vector[0].tolist()
        if len(result) != EMBEDDING_DIM:
            raise EmbeddingServiceUnavailableError(
                f"embedding dimension mismatch: got {len(result)}, expected {EMBEDDING_DIM}"
            )
        return result


@lru_cache(maxsize=1)
def get_embedding_service() -> EmbeddingService:
    """Process-wide singleton. The model load itself is deferred to the
    first `ensure_loaded()`/`embed_query()` call, not to this factory."""
    return EmbeddingService()
