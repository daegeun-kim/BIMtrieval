"""Backend reader for the repository-owned semantic access contract (task26 §3.2).

The contract is shared DATA under `semantic_contract/` at the repository root;
ingestion has its own independent reader. The backend never imports ingestion
code and never writes the contract.
"""

from __future__ import annotations

import json
import os
from functools import lru_cache
from pathlib import Path
from typing import Any

ACCESS_CONTRACT_VERSION = "v001"

_BACKEND_ROOT = Path(__file__).resolve().parents[3]


def find_contract_path(version: str = ACCESS_CONTRACT_VERSION) -> Path:
    configured = os.environ.get("semantic_contract_root") or os.environ.get(
        "SEMANTIC_CONTRACT_ROOT"
    )
    if configured:
        return Path(configured) / f"access_contract_{version}.json"
    for candidate in (_BACKEND_ROOT, *_BACKEND_ROOT.parents):
        path = candidate / "semantic_contract" / f"access_contract_{version}.json"
        if path.is_file():
            return path
    raise FileNotFoundError(
        f"semantic_contract/access_contract_{version}.json not found above {_BACKEND_ROOT}"
    )


@lru_cache(maxsize=4)
def load_access_contract(version: str = ACCESS_CONTRACT_VERSION) -> dict[str, Any]:
    with open(find_contract_path(version), "rb") as handle:
        contract = json.loads(handle.read().decode("utf-8"))
    if contract.get("contract_version") != version:
        raise ValueError(
            f"access contract declares version {contract.get('contract_version')!r}, "
            f"expected {version!r}"
        )
    return contract


def declared_accessors(version: str = ACCESS_CONTRACT_VERSION) -> dict[str, dict[str, Any]]:
    return load_access_contract(version)["accessors"]


def accessor_declaration(accessor: str, version: str = ACCESS_CONTRACT_VERSION) -> dict[str, Any]:
    accessors = declared_accessors(version)
    if accessor not in accessors:
        raise KeyError(f"accessor {accessor!r} is not declared by access contract {version}")
    return accessors[accessor]


def coverage_semantics(version: str = ACCESS_CONTRACT_VERSION) -> dict[str, dict[str, Any]]:
    return load_access_contract(version)["coverage_states"]


__all__ = [
    "ACCESS_CONTRACT_VERSION",
    "accessor_declaration",
    "coverage_semantics",
    "declared_accessors",
    "find_contract_path",
    "load_access_contract",
]
