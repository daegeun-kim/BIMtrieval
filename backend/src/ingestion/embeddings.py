"""Lazy access to the existing embedding/vectorization implementation.

Canonical implementation: src/bim_rag/stage2_embed.py, which imports torch
and sentence-transformers at module scope. `pipeline_structured.ifc_to_db()`
already defers this import to avoid loading torch just to do structured
import; this shim preserves that property so importing `ingestion.embeddings`
(or anything that transitively imports it) never pulls in torch/GPU
dependencies unless `get_run_vector_phase()` is actually called.
"""

from __future__ import annotations

from typing import Any, Callable


def get_run_vector_phase() -> Callable[..., dict[str, Any]]:
    """Return `bim_rag.stage2_embed.run_vector_phase`, importing it on first use."""
    from bim_rag.stage2_embed import run_vector_phase

    return run_vector_phase
