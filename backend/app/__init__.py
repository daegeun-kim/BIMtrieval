"""BIM RAG query backend application package.

Independent Poetry application (Task 09). The only runtime integration with
ingestion is the shared PostgreSQL database; no `bim_rag` code is imported.
"""

# Thread/OpenMP controls must be set BEFORE torch or any MKL-backed library is
# imported anywhere in this process. Without them, the bge-m3 query-embedding
# forward pass dies on Windows with an unhandled native exception (0xc06d007f,
# "OMP: Error #15 — libiomp5md.dll already initialized") the moment two runtimes
# that each bundle their own OpenMP meet — which is what happens once torch and
# the MKL-linked numpy in the retrieval path load together. The model LOADS
# fine; the first inference matmul is what crashes, so the failure looks like a
# silent hang right after "Loading weights 100%".
#
# The ingestion project sets the same guard in `bim_rag.config` for exactly this
# reason; the backend must do it independently because it never imports that
# module. `setdefault` so an explicit environment override still wins.
import os as _os

_os.environ.setdefault("KMP_DUPLICATE_LIB_OK", "TRUE")
_os.environ.setdefault("OMP_NUM_THREADS", "1")
_os.environ.setdefault("MKL_NUM_THREADS", "1")
_os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")
# The load-bearing one for the retrieval path. `KMP_DUPLICATE_LIB_OK` only
# suppresses the init-time abort; a numpy/MKL matmul (e.g. the cosine top-k over
# the ontology index in `semantic/resolution.py`) can still SEH-crash mid-region
# when MKL spins up its own OpenMP team beside torch's. Forcing MKL sequential
# removes the second team entirely, so the two runtimes never contend. This is a
# hard native crash `try/except` cannot catch, so it MUST be prevented here.
_os.environ.setdefault("MKL_THREADING_LAYER", "SEQUENTIAL")
