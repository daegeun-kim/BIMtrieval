"""Reader for the repository-owned semantic access contract (task26 §3.2).

The contract is DATA shared between ingestion and backend; each side has its
own small reader so neither package imports the other. This one resolves the
`semantic_contract/` directory by walking up from the ingestion project root,
the same way the shared `.env` is found.
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

ACCESS_CONTRACT_VERSION = "v001"

_INGESTION_ROOT = Path(__file__).resolve().parents[2]


def find_contract_path(version: str = ACCESS_CONTRACT_VERSION) -> Path:
    for candidate in (_INGESTION_ROOT, *_INGESTION_ROOT.parents):
        path = candidate / "semantic_contract" / f"access_contract_{version}.json"
        if path.is_file():
            return path
    raise FileNotFoundError(
        f"semantic_contract/access_contract_{version}.json not found above {_INGESTION_ROOT}"
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


def accessor_declaration(accessor: str, version: str = ACCESS_CONTRACT_VERSION) -> dict[str, Any]:
    accessors = load_access_contract(version)["accessors"]
    if accessor not in accessors:
        raise KeyError(f"accessor {accessor!r} is not declared by access contract {version}")
    return accessors[accessor]


def operators_for(data_type: str, version: str = ACCESS_CONTRACT_VERSION) -> list[str]:
    return list(load_access_contract(version)["operators_by_data_type"].get(data_type, ()))
