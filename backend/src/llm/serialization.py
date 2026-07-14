"""JSON serialization for LLM context/evidence payloads.

The planner and answer calls send their inputs as a JSON string in the user
message. This helper handles enums, pydantic models, and dataclasses, and is
the single place that guarantees payloads are plain JSON — no secrets, no
raw SQL, no full canonical JSON are ever placed on these payloads by callers.
"""

from __future__ import annotations

import dataclasses
import json
from enum import Enum
from typing import Any

from pydantic import BaseModel


def _default(obj: Any) -> Any:
    if isinstance(obj, BaseModel):
        return obj.model_dump(mode="json")
    if dataclasses.is_dataclass(obj) and not isinstance(obj, type):
        return dataclasses.asdict(obj)
    if isinstance(obj, Enum):
        return obj.value
    if isinstance(obj, set):
        return sorted(obj)
    return str(obj)


def dumps_context(payload: dict[str, Any]) -> str:
    return json.dumps(payload, default=_default, ensure_ascii=False, indent=2)
