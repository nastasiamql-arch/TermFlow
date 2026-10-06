import re

from termflow.core.errors import ValidationError
from termflow.validators.common import parse_tsv

COPY_READY = "=== COPY-READY TSV ==="


def validate_step_b(raw: str, input_rows: list[list[str]]) -> list[list[str]]:
    # Analysis is allowed, but the copy-ready region must be clearly delimited.
    heading = r"(?m)^[ \t]*(?:#{1,6}[ \t]+)?(?:=== COPY-READY TSV ===|(?:ส่วนที่[ \t]*3:[ \t]*)?ผลลัพธ์ TSV[^\n]*)[ \t]*$"
    markers = list(re.finditer(heading, raw))
    if len(markers) > 1:
        raise ValidationError(["Expected exactly one copy-ready TSV section"])
    block = raw[markers[0].end():].strip() if markers else raw.strip()
    if block.startswith("```"):
        match = re.match(r"```(?:text|tsv)?[ \t]*\r?\n(.*?)\r?\n```(?=\s|$)", block, flags=re.IGNORECASE | re.DOTALL)
        if not match:
            raise ValidationError(["Markdown contamination in copy-ready block"])
        trailing = block[match.end():]
        if "\t" in trailing or (not markers and trailing.strip()):
            raise ValidationError(["Ambiguous content after copy-ready block"])
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
