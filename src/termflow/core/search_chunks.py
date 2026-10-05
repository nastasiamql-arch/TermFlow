import re
from bisect import bisect_left, bisect_right
from dataclasses import dataclass


@dataclass(frozen=True)
class SourceChunk:
    """One core source range and its context-expanded request text."""

    index: int
    core_start: int
    core_end: int
    request_start: int
    request_end: int
    text: str


_PARAGRAPH_BREAK = re.compile(r"(?:\r?\n[ \t]*){2,}")
_LINE_BREAK = re.compile(r"\r?\n")


def _preferred_boundaries(source: str, needed: int) -> list[int]:
    paragraphs = [match.end() for match in _PARAGRAPH_BREAK.finditer(source)]
    if len(paragraphs) >= needed:
        return paragraphs
    lines = [match.end() for match in _LINE_BREAK.finditer(source)]
    return lines if len(lines) >= needed else []


def _core_boundaries(source: str, count: int, natural: list[int]) -> list[int]:
    length = len(source)
    if length < count:
        return [round(index * length / count) for index in range(count + 1)]

    boundaries = [0]
    for index in range(1, count):
        target = round(index * length / count)
        lower = boundaries[-1] + 1
        upper = length - (count - index)
        options = [point for point in natural if lower <= point <= upper]
        point = min(options, key=lambda value: (abs(value - target), value)) if options else min(max(target, lower), upper)
        boundaries.append(point)
    boundaries.append(length)
    return boundaries


def _request_bounds(core_start: int, core_end: int, boundaries: list[int], length: int, overlap_units: int) -> tuple[int, int]:
    if overlap_units <= 0 or not boundaries:
        return core_start, core_end

    start_unit = bisect_right(boundaries, core_start)
    start_boundary_index = max(0, start_unit - overlap_units - 1)
    request_start = boundaries[start_boundary_index]

    end_unit = bisect_left(boundaries, core_end)
    following_boundary_index = end_unit + overlap_units
    request_end = boundaries[following_boundary_index] if following_boundary_index < len(boundaries) else length
    return min(request_start, core_start), max(request_end, core_end)


def split_source(source: str, count: int = 10, overlap_units: int = 1) -> list[SourceChunk]:
    """Split SOURCE into balanced, ordered core ranges with small context overlap.

    Paragraph breaks are preferred, line breaks are used when there are too
    few paragraphs, and Unicode code-point positions are the final fallback.
    Empty ranges are retained so the UI always has ten visible slots; callers
    should mark those slots skipped instead of sending empty AI requests.
    """
    if count < 1:
        raise ValueError("count must be at least 1")
    if overlap_units < 0:
        raise ValueError("overlap_units cannot be negative")

    length = len(source)
    natural = _preferred_boundaries(source, count - 1)
    cores = _core_boundaries(source, count, natural)
    chunks = []
    for index, (core_start, core_end) in enumerate(zip(cores, cores[1:]), start=1):
        request_start, request_end = _request_bounds(core_start, core_end, natural, length, overlap_units)
        chunks.append(
            SourceChunk(
                index=index,
                core_start=core_start,
                core_end=core_end,
                request_start=request_start,
                request_end=request_end,
                text=source[request_start:request_end],
            )
        )
    return chunks
