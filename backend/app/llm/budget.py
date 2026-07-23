"""Request-scoped deterministic provider cost budget (task26 §9.5).

Tracks the ACTUAL cost of every completed call from its captured usage, and
conservatively estimates the next call from serialized prompt bytes, cache
expectations, configured maximum output, and the versioned rate card. The
budget's job is to guarantee the USD limit is respected without dropping
semantic requirements: prompt compaction is the primary control, this gate is
the final safeguard.

Rules (§9.5):

- reserve the final answer call before permitting a correction;
- skip the correction when the conservative estimate would exceed the limit;
- unknown pricing is never reported as zero — an unpriceable optional call is
  simply not affordable;
- every estimate, reservation, actual, and skip decision is logged.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app.llm.pricing import cost_for_call

__all__ = ["RequestBudget", "BudgetDecision", "DEFAULT_REQUEST_BUDGET_USD"]

DEFAULT_REQUEST_BUDGET_USD = 0.03

#: Conservative bytes-per-token for compact JSON prompts (over-estimates
#: tokens, which over-estimates cost — the safe direction for a gate).
_BYTES_PER_TOKEN = 3

#: Realistic expected structured-output size for the estimate. Pricing the full
#: `max_output_tokens` (often 8-16k) at the output rate makes the estimate wildly
#: exceed actual usage (~1-2k tokens) and would skip every correction, defeating
#: §9.5's "the budget gate is the final safeguard, not a reason to drop semantic
#: requirements". This is conservative over the typical actual output while
#: staying usable; it is still capped by the configured maximum below.
_TYPICAL_OUTPUT_TOKENS = 3000


@dataclass(frozen=True)
class BudgetDecision:
    kind: str  # "actual" | "estimate" | "reserve" | "skip"
    role: str
    usd: float | None
    detail: str

    def to_payload(self) -> dict[str, Any]:
        return {"kind": self.kind, "role": self.role, "usd": self.usd, "detail": self.detail}


@dataclass
class RequestBudget:
    limit_usd: float = DEFAULT_REQUEST_BUDGET_USD
    spent_usd: float = 0.0
    decisions: list[BudgetDecision] = field(default_factory=list)

    # -- actuals -------------------------------------------------------------

    def track_actual(self, role: str, usage: Any) -> None:
        """Record one completed call's actual cost from captured usage."""
        cost = usage.cost() if hasattr(usage, "cost") else None
        usd = getattr(cost, "usd", None)
        if usd is not None:
            self.spent_usd += usd
            detail = f"actual cost ${usd:.6f}"
        else:
            detail = (
                "actual cost unavailable: "
                + (getattr(cost, "unavailable_reason", None) or "no usage captured")
            )
        self.decisions.append(BudgetDecision("actual", role, usd, detail))

    # -- estimates -----------------------------------------------------------

    def estimate_call(
        self,
        role: str,
        *,
        model: str,
        stable_prefix_bytes: int,
        dynamic_bytes: int,
        max_output_tokens: int,
        expect_cached_prefix: bool = False,
        service_tier: str | None = None,
        expected_output_tokens: int | None = None,
    ) -> float | None:
        """Conservative USD estimate for one prospective call, or None when
        the rate card cannot price it (never zero, §9.5).

        Output is priced at a realistic expected size (bounded by the configured
        maximum), not the full maximum, so a small structured completion is not
        estimated as a maxed-out one.
        """
        stable_tokens = stable_prefix_bytes // _BYTES_PER_TOKEN
        dynamic_tokens = dynamic_bytes // _BYTES_PER_TOKEN
        output_tokens = min(
            max_output_tokens, expected_output_tokens or _TYPICAL_OUTPUT_TOKENS
        )
        if expect_cached_prefix:
            cost = cost_for_call(
                model=model,
                uncached_input_tokens=dynamic_tokens,
                cached_input_tokens=stable_tokens,
                cache_write_tokens=0,
                output_tokens=output_tokens,
                service_tier=service_tier,
            )
        else:
            cost = cost_for_call(
                model=model,
                uncached_input_tokens=stable_tokens + dynamic_tokens,
                cached_input_tokens=0,
                cache_write_tokens=0,
                output_tokens=output_tokens,
                service_tier=service_tier,
            )
        usd = cost.usd
        self.decisions.append(
            BudgetDecision(
                "estimate",
                role,
                usd,
                f"~{stable_tokens + dynamic_tokens} input tokens, "
                f"{max_output_tokens} max output"
                + ("" if usd is not None else f"; unpriceable: {cost.unavailable_reason}"),
            )
        )
        return usd

    # -- gating --------------------------------------------------------------

    def allows_correction(
        self, correction_estimate_usd: float | None, answer_reserve_usd: float | None
    ) -> bool:
        """True when spending the correction still leaves the answer payable.

        Unknown pricing on either side is NOT treated as zero — the optional
        correction is skipped rather than risked (§9.5).
        """
        if correction_estimate_usd is None or answer_reserve_usd is None:
            self.decisions.append(
                BudgetDecision(
                    "skip",
                    "correction",
                    None,
                    "correction skipped: pricing unavailable for a required estimate",
                )
            )
            return False
        projected = self.spent_usd + correction_estimate_usd + answer_reserve_usd
        if projected > self.limit_usd:
            self.decisions.append(
                BudgetDecision(
                    "skip",
                    "correction",
                    correction_estimate_usd,
                    f"correction skipped: projected ${projected:.6f} exceeds "
                    f"budget ${self.limit_usd:.6f}",
                )
            )
            return False
        self.decisions.append(
            BudgetDecision(
                "reserve",
                "grounded_answerer",
                answer_reserve_usd,
                f"answer reserve held; projected ${projected:.6f} within "
                f"${self.limit_usd:.6f}",
            )
        )
        return True

    def to_payload(self) -> dict[str, Any]:
        return {
            "limit_usd": self.limit_usd,
            "spent_usd": round(self.spent_usd, 6),
            "decisions": [d.to_payload() for d in self.decisions],
        }
