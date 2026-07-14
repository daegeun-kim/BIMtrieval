"""Bounded async execution of independent query paths (spec_v005 §8).

Independent SQL and RAG work runs concurrently on worker threads (each path
opens its own database session, since SQLAlchemy Sessions are not shared across
threads). Each task has its own timeout; one path failing or timing out is
captured as an explicit `TaskResult(ok=False, ...)` rather than cancelling the
siblings or silently pretending the path returned no matches (spec_v005 §8,
§17).

Dependent modes do NOT use this helper — the orchestrator sequences them
directly, because one path consumes the other's candidates.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any, Callable


@dataclass
class TaskResult:
    ok: bool
    value: Any = None
    error: str | None = None


def _sanitize(exc: BaseException) -> str:
    if isinstance(exc, asyncio.TimeoutError):
        return "path timed out"
    return f"{type(exc).__name__}: {str(exc)[:200]}"


def run_parallel(
    tasks: dict[str, Callable[[], Any]], timeout_s: float
) -> dict[str, TaskResult]:
    """Run each 0-arg callable concurrently on a thread; return per-name results.

    Never raises for an individual task failure — failures become
    TaskResult(ok=False, error=...). Order of `tasks` is preserved in the result.
    """
    if not tasks:
        return {}

    async def _one(fn: Callable[[], Any]) -> TaskResult:
        try:
            value = await asyncio.wait_for(asyncio.to_thread(fn), timeout_s)
            return TaskResult(ok=True, value=value)
        except Exception as exc:  # noqa: BLE001 - one path's failure is not fatal
            return TaskResult(ok=False, error=_sanitize(exc))

    async def _runner() -> dict[str, TaskResult]:
        names = list(tasks.keys())
        results = await asyncio.gather(*[_one(tasks[n]) for n in names])
        return dict(zip(names, results))

    return asyncio.run(_runner())
