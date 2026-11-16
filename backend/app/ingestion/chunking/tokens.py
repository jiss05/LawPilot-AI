"""
Approximate token counting.

WHAT IS A TOKEN?
Language models don't read letters or whole words; they read "tokens",
pieces of words. "compensation" might be 2-3 tokens, "the" is 1. Every
model has a limit on how many tokens it can take in, and an embedding
model gives better vectors for focused, medium-sized text.

WHY APPROXIMATE?
Exact counts depend on the model's own tokenizer, and the embedding model
is not chosen yet (BRD §18.3). For English, 1 token is roughly 4
characters, which is accurate enough to keep chunk sizes sensible. When
the model is chosen, only this one function needs to change.
"""

import math

CHARS_PER_TOKEN = 4
METHOD = "chars/4"  # saved in chunk metadata so we know how counts were made


def estimate_tokens(text: str) -> int:
    """Approximate number of tokens in `text` (at least 1 for non-empty text)."""
    stripped = text.strip()
    if not stripped:
        return 0
    return max(1, math.ceil(len(stripped) / CHARS_PER_TOKEN))
