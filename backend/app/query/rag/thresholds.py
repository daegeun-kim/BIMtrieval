"""Named, configurable similarity threshold profiles (spec_v004 §8).

No universal BGE-M3 threshold is asserted without calibration. Both values
were calibrated against this project's real stored documents and an 8
question representative set — see
`backend/src/evaluation/rag_calibration_v001.jsonl` and the full
precision/recall table in `docs/architecture_v004.md`.

- `default_v001` (0.50): retains full observed recall (candidates that would
  pass at lower thresholds all still pass) while excluding the long tail of
  weak matches — every calibration question with genuine signal reached
  precision 1.0 at or below this value.
- `high_precision_v001` (0.55): trades recall for precision (aggregate
  precision 0.4 -> 0.8) — useful when false positives are costlier than
  missed candidates, at the cost of losing entire weakly-separated classes
  (e.g. walls dropped out entirely in calibration at this threshold).
"""

from __future__ import annotations

from app.shared.errors import UnsupportedOperationError

THRESHOLD_PROFILES: dict[str, float] = {
    "default_v001": 0.50,
    "high_precision_v001": 0.55,
}


def get_threshold(profile: str) -> float:
    if profile not in THRESHOLD_PROFILES:
        raise UnsupportedOperationError(
            f"unknown similarity threshold profile {profile!r}; "
            f"available: {sorted(THRESHOLD_PROFILES)}"
        )
    return THRESHOLD_PROFILES[profile]
