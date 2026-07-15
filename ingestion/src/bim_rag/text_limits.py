"""Shared token-budget enforcement for entity/relationship document generation.

Used only when a real tokenizer is supplied (production embedding path).
Callers that omit the tokenizer keep the char-budget-only behavior in
templates.py / rel_templates.py unchanged.
"""

from __future__ import annotations

from typing import Any, Protocol

# BAAI/bge-m3 supports up to 8192 tokens. This ceiling is deliberately far
# below that so a single unexpectedly long document can never expand the
# effective per-batch workload close to the model limit.
MAX_TOKENS = 2000


class Tokenizes(Protocol):
    def encode(self, text: str) -> Any: ...


def apply_token_budget(
    priority_ordered_sentences: list[str],
    tokenizer: Tokenizes,
    max_tokens: int = MAX_TOKENS,
) -> tuple[list[str], bool, int]:
    """Keep sentences (highest priority first) until max_tokens would be exceeded.

    Returns (kept_sentences, truncated, encoded_token_count).
    """
    kept: list[str] = []
    running = 0
    truncated = False
    for sentence in priority_ordered_sentences:
        n = len(tokenizer.encode(sentence))
        if running + n > max_tokens:
            truncated = True
            continue
        kept.append(sentence)
        running += n
    return kept, truncated, running


def count_tokens(sentences: list[str], tokenizer: Tokenizes) -> int:
    return sum(len(tokenizer.encode(s)) for s in sentences)
