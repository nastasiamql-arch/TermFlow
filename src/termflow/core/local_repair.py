"""Deterministic whitespace-only output cleanup; never alters TSV cell values."""

from termflow.validators.step_a_validator import NEW, UPDATE
from termflow.validators.step_b_validator import COPY_READY


def repair_formatting(raw: str, workflow: str) -> str | None:
    normalized = raw.replace("\r\n", "\n").replace("\r", "\n")
    lines = normalized.split("\n")
    while lines and not lines[-1].strip():
        lines.pop()
    headings = (NEW, UPDATE) if workflow == "A" else (COPY_READY,)
    for index, line in enumerate(lines):
        candidate = line.strip()
        if candidate.startswith("#"):
            candidate = candidate.lstrip("#").strip()
        if candidate in headings:
            lines[index] = candidate
    repaired = "\n".join(lines)
    return repaired if repaired != raw else None
