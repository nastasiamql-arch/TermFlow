import re

from termflow.core.errors import ValidationError
from termflow.validators.common import parse_tsv

COPY_READY = "=== COPY-READY TSV ==="


def validate_step_b(raw: str, input_rows: list[list[str]], *, allow_removals: bool = False, flexible: bool = False) -> list[list[str]]:
    # Analysis is allowed, but the copy-ready region must be clearly delimited.
    heading = r"(?m)^[ \t]*(?:#{1,6}[ \t]+)?(?:=== COPY-READY TSV ===|(?:ส่วนที่[ \t]*3:[ \t]*)?ผลลัพธ์ TSV[^\n]*)[ \t]*\r?$"
    markers = list(re.finditer(heading, raw))
    if len(markers) > 1:
        raise ValidationError(["Expected exactly one copy-ready TSV section"])
    block = raw[markers[0].end():].strip() if markers else raw.strip()
    if block.startswith("```"):
        languages = r"(?:text|tsv|csv|markdown|md|json)?" if flexible else r"(?:text|tsv)?"
        match = re.match(r"```" + languages + r"[ \t]*\r?\n(.*?)^```[ \t]*\r?$", block,
                         flags=re.IGNORECASE | re.DOTALL | re.MULTILINE)
        if not match:
            raise ValidationError(["Markdown contamination in copy-ready block"])
        trailing = block[match.end():]
        if "\t" in trailing or (not markers and trailing.strip()):
            raise ValidationError(["Ambiguous content after copy-ready block"])
        block = match.group(1).strip()
    elif "```" in block:
        raise ValidationError(["Markdown contamination in copy-ready block"])
    if flexible:
        from termflow.validators.formats import normalize_rows
        block = normalize_rows(block, 3)
    elif "|" in block:
        raise ValidationError(["Markdown contamination in copy-ready block"])
    try:
        out = parse_tsv(block, 3)
    except ValueError as exc:
        raise ValidationError([str(exc)]) from exc
    expected = [row[0] for row in input_rows]
    found = [row[0] for row in out]
    if len(out) > len(input_rows) or (not allow_removals and len(out) != len(input_rows)):
        raise ValidationError([f"Expected {len(input_rows)} output rows; Received {len(out)}"])
    if len(set(found)) != len(found):
        raise ValidationError(["Duplicate CN"])
    if (allow_removals and not set(found).issubset(expected)) or (not allow_removals and set(found) != set(expected)):
        raise ValidationError(["Missing or unknown CN"])
    for cn, th, note in out:
        if cn not in expected:
            raise ValidationError([f"Unknown CN: {cn}"])
        if not th.strip():
            raise ValidationError([f"Missing TH for {cn}"])
        if not note.strip():
            raise ValidationError([f"Missing NOTE for {cn}"])
    return out
