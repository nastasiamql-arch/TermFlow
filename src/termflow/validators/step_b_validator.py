import re

from termflow.core.errors import ValidationError
from termflow.validators.common import parse_tsv

COPY_READY = "=== COPY-READY TSV ==="


def validate_step_b(raw: str, input_rows: list[list[str]]) -> list[list[str]]:
    # Analysis is allowed, but the copy-ready region must be clearly delimited.
    if raw.count(COPY_READY) != 1:
        raise ValidationError([f"Expected one '{COPY_READY}' block"])
    block = raw.split(COPY_READY, 1)[1].strip()
    if block.startswith("```"):
        match = re.fullmatch(r"```(?:text|tsv)?[ \t]*\r?\n(.*?)\r?\n```", block, flags=re.IGNORECASE | re.DOTALL)
        if not match:
            raise ValidationError(["Markdown contamination in copy-ready block"])
        block = match.group(1).strip()
    elif "```" in block:
        raise ValidationError(["Markdown contamination in copy-ready block"])
    if "|" in block:
        raise ValidationError(["Markdown contamination in copy-ready block"])
    try:
        out = parse_tsv(block, 3)
    except ValueError as exc:
        raise ValidationError([str(exc)]) from exc
    expected = [row[0] for row in input_rows]
    found = [row[0] for row in out]
    if len(out) != len(input_rows):
        raise ValidationError([f"Expected {len(input_rows)} output rows; Received {len(out)}"])
    if len(set(found)) != len(found):
        raise ValidationError(["Duplicate CN"])
    if set(found) != set(expected):
        raise ValidationError(["Missing or unknown CN"])
    for cn, th, note in out:
        if cn not in expected:
            raise ValidationError([f"Unknown CN: {cn}"])
        if not th.strip():
            raise ValidationError([f"Missing TH for {cn}"])
        if not note.strip():
            raise ValidationError([f"Missing NOTE for {cn}"])
    return out
