"""Hybrid-orchestration errors (spec_v005 §17).

A hybrid run distinguishes *degraded* paths (one path unavailable, e.g. RAG
embedding down) from a *fatal* orchestration failure. Degraded paths are
represented explicitly in the evidence, never silently swallowed (spec_v005
§8, §17): the surviving paths still answer, with a warning.
"""

from __future__ import annotations


class OrchestrationError(RuntimeError):
    """A whole orchestration could not proceed (e.g. every declared path failed)."""


class EmptyIntersectionNotUnion(Exception):
    """Internal sentinel: an intersection produced no ids. Never reinterpreted as
    a union (spec_v005 §9) — the orchestrator reports the empty result honestly."""
