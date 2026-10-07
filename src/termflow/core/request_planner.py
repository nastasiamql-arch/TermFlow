from dataclasses import dataclass
from math import ceil


@dataclass(frozen=True)
class SearchPlan:
    chunk_count: int
    estimated_input_tokens: int
    estimated_total_tokens: int
    warning: str = ""


def estimate_tokens(text: str) -> int:
    """Conservative mixed-script estimate; replace with provider tokenizers when available."""
    return ceil(len(text) / 2)


def plan_search(prompt: str, vocab: str, source: str, context_window: int, output_reserve: int = 8192) -> SearchPlan:
    if context_window <= output_reserve:
        raise ValueError("Context window must exceed the output reserve")
    fixed_tokens = estimate_tokens(prompt) + estimate_tokens(vocab) + 256
    source_tokens = estimate_tokens(source)
    per_chunk_source_capacity = context_window - output_reserve - fixed_tokens
    if per_chunk_source_capacity <= 0:
        raise ValueError("Prompt and VOCAB exceed the configured context budget")
    count = max(1, ceil(source_tokens / per_chunk_source_capacity))
    estimated_input = fixed_tokens + ceil(source_tokens / count)
    estimated_total = fixed_tokens * count + source_tokens
    warning = "Prompt and VOCAB are repeated for each request." if count > 1 else ""
    return SearchPlan(count, estimated_input, estimated_total, warning)
