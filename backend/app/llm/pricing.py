"""Versioned local pricing registry for OpenAI API cost reporting (task25 §6.1).

The terminal prints the calculated USD cost of every request beside the existing
token summary. That number is computed HERE, from the captured usage and a rate
card recorded in this file — never from a network lookup during a user query, so
a request never waits on a pricing endpoint and cost is reproducible from the
recorded rates alone.

Design rules from §6.1, all load-bearing:

- rates are keyed by EXACT model id and service tier;
- billable token buckets are mutually exclusive — cached and cache-write tokens
  are never also charged as uncached input;
- reasoning tokens are billed as output and are already inside the provider's
  output total, so they are visible in diagnostics but never added on top;
- an unknown model/tier prints `cost unavailable` with a reason. It never
  becomes `$0.00`, because a silent zero reads as "free" rather than "unknown".

The OpenAI billing dashboard remains the external billing authority; this value
is the request cost calculated from captured usage and the recorded rate card.
"""

from __future__ import annotations

from dataclasses import dataclass

#: Bump when any rate changes, so a report can be tied to the exact card used.
PRICING_REGISTRY_VERSION = "2026-07-21"

#: Where the rates came from and when they were last checked by a human.
PRICING_SOURCE_URL = "https://developers.openai.com/api/docs/pricing"
PRICING_VERIFIED_DATE = "2026-07-21"

#: The tier assumed when the provider does not report one.
DEFAULT_SERVICE_TIER = "standard"

#: Provider tier names that all bill at the standard rate card. The Responses API
#: reports `service_tier="default"` (and `"auto"` resolves to it) for an ordinary
#: request; both mean the standard rates recorded below, so they are normalized
#: rather than treated as an unknown tier that would suppress the cost.
_STANDARD_TIER_ALIASES = frozenset({"standard", "default", "auto", "", "none"})


def _normalize_tier(service_tier: str | None) -> str:
    if service_tier is None:
        return DEFAULT_SERVICE_TIER
    if service_tier.strip().lower() in _STANDARD_TIER_ALIASES:
        return DEFAULT_SERVICE_TIER
    return service_tier


@dataclass(frozen=True)
class ModelRates:
    """USD per 1,000,000 tokens for one model at one service tier.

    A `None` rate means "not on the recorded card". It is not zero: a bucket
    that carries tokens at a `None` rate makes the whole call `cost unavailable`.
    """

    uncached_input: float | None
    cached_input: float | None
    cache_write: float | None
    output: float | None
    #: Human note recorded with the rate, e.g. a rate the card does not list.
    note: str = ""


#: (model, service_tier) -> rates. Rates are USD per 1,000,000 tokens.
#:
#: gpt-5.6-sol / gpt-5.6-terra are the Task 25 target binder/answer models, with
#: rates transcribed from task25 §6.1 and re-verified against the live pricing
#: docs on 2026-07-21. gpt-5-nano is the model the CURRENT pipeline still uses;
#: its input/output rates were confirmed against 2026 pricing sources. gpt-5-nano
#: is not on the flagship rate card's cache columns, so its cached/cache-write
#: rates are left unrecorded — the current pipeline uses Chat Completions with no
#: prompt caching, so those buckets are always empty and never contribute cost.
_REGISTRY: dict[tuple[str, str], ModelRates] = {
    ("gpt-5.6-sol", "standard"): ModelRates(
        uncached_input=5.00, cached_input=0.50, cache_write=6.25, output=30.00
    ),
    ("gpt-5.6-terra", "standard"): ModelRates(
        uncached_input=2.50, cached_input=0.25, cache_write=3.125, output=15.00
    ),
    # Cost-reduced roles selected by the owner over the §6 flagship defaults.
    # Rates verified against the live pricing docs on 2026-07-21.
    ("gpt-5.4-nano", "standard"): ModelRates(
        uncached_input=0.20, cached_input=0.02, cache_write=1.25, output=1.25
    ),
    ("gpt-5.4-mini", "standard"): ModelRates(
        uncached_input=0.75, cached_input=0.075, cache_write=4.50, output=4.50
    ),
    ("gpt-5-nano", "standard"): ModelRates(
        uncached_input=0.05,
        cached_input=None,
        cache_write=None,
        output=0.40,
        note="input/output confirmed 2026; not on the flagship cache rate card",
    ),
}


@dataclass(frozen=True)
class CallCost:
    """The costed result of one LLM call."""

    model: str
    service_tier: str
    usd: float | None
    #: Present when `usd is None` — why the cost could not be computed.
    unavailable_reason: str | None = None
    #: Per-bucket contributions, for diagnostics and tests.
    breakdown: dict[str, float] | None = None

    @property
    def available(self) -> bool:
        return self.usd is not None

    def formatted(self) -> str:
        """`$0.001234` or `cost unavailable (reason)` — never `$0.00` for unknown."""
        if self.usd is None:
            return f"cost unavailable ({self.unavailable_reason})"
        return f"${self.usd:.6f}"


def get_rates(model: str, service_tier: str | None = None) -> ModelRates | None:
    tier = _normalize_tier(service_tier)
    return _REGISTRY.get((model, tier))


def cost_for_call(
    *,
    model: str,
    uncached_input_tokens: int = 0,
    cached_input_tokens: int = 0,
    cache_write_tokens: int = 0,
    output_tokens: int = 0,
    service_tier: str | None = None,
) -> CallCost:
    """USD for one call from mutually exclusive billable token buckets (§6.1).

    Callers MUST pass non-overlapping buckets derived from the usage object:
    cached and cache-write tokens are subtracted from uncached input upstream, so
    no token is charged twice. `output_tokens` is the provider's billable output
    total, which already includes reasoning tokens.
    """
    tier = _normalize_tier(service_tier)
    rates = _REGISTRY.get((model, tier))
    if rates is None:
        return CallCost(
            model=model,
            service_tier=tier,
            usd=None,
            unavailable_reason=f"no recorded rate for model {model!r} at tier {tier!r}",
        )

    buckets = (
        ("uncached_input", uncached_input_tokens, rates.uncached_input),
        ("cached_input", cached_input_tokens, rates.cached_input),
        ("cache_write", cache_write_tokens, rates.cache_write),
        ("output", output_tokens, rates.output),
    )

    breakdown: dict[str, float] = {}
    total = 0.0
    for name, tokens, rate in buckets:
        if not tokens:
            # An empty bucket contributes nothing even if its rate is unrecorded,
            # so a model priced only for input/output still costs correctly when
            # no cached or cache-write tokens were billed.
            continue
        if rate is None:
            return CallCost(
                model=model,
                service_tier=tier,
                usd=None,
                unavailable_reason=(
                    f"model {model!r} has {tokens} {name} tokens but no recorded "
                    f"{name} rate at tier {tier!r}"
                ),
            )
        contribution = tokens / 1_000_000 * rate
        breakdown[name] = contribution
        total += contribution

    return CallCost(model=model, service_tier=tier, usd=total, breakdown=breakdown)


def cost_for_request(calls: list[CallCost]) -> CallCost | None:
    """Sum per-call costs into one request total (§6.1).

    If ANY call is `cost unavailable`, the request total is too — a partial sum
    would understate the real spend and read as authoritative.
    """
    if not calls:
        return None
    if any(not c.available for c in calls):
        reasons = "; ".join(c.unavailable_reason for c in calls if not c.available)
        return CallCost(
            model="request",
            service_tier=DEFAULT_SERVICE_TIER,
            usd=None,
            unavailable_reason=reasons,
        )
    total = sum(c.usd or 0.0 for c in calls)
    return CallCost(model="request", service_tier=DEFAULT_SERVICE_TIER, usd=total)


def cost_from_simple_usage(
    model: str,
    prompt_tokens: int,
    completion_tokens: int,
    *,
    service_tier: str | None = None,
) -> CallCost:
    """Cost a Chat-Completions-style usage record (task24 pipeline, §6.1 subset).

    That API reports only aggregate prompt/completion counts with no cached
    breakdown, and this pipeline uses no prompt caching, so every prompt token is
    billed as uncached input and every completion token as output. This is the
    correct full cost for the current pipeline, and an UPPER bound for any future
    request that does use caching.
    """
    return cost_for_call(
        model=model,
        uncached_input_tokens=prompt_tokens,
        output_tokens=completion_tokens,
        service_tier=service_tier,
    )
