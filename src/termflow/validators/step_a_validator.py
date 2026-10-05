from termflow.core.errors import ValidationError
from termflow.validators.common import parse_tsv

NEW = "=== คำศัพท์ใหม่ ==="
UPDATE = "=== คำศัพท์อัปเดต ==="
EMPTY = "— ไม่มีรายการ —"
SEX_VALUES = {"ชาย", "หญิง", "ยังไม่ยืนยัน", "-"}


def validate_step_a(raw: str) -> tuple[list[list[str]], list[list[str]]]:
    errors: list[str] = []
    lines = raw.splitlines()
    # Prompt A's source of truth explicitly requires the structured result to
    # be wrapped in one code block. Remove only that outer wrapper; all content
    # inside remains subject to the exact same strict TSV validation below.
    if lines and lines[0].strip() in {"```", "```text"}:
        if not lines[-1].strip() == "```" or len(lines) < 3:
            raise ValidationError(["Expected one complete outer code block"])
        lines = lines[1:-1]
    elif any(line.strip() in {"```", "```text"} for line in lines):
        raise ValidationError(["Unexpected Markdown code fence"])
    if lines.count(NEW) != 1:
        errors.append(f"Expected '{NEW}' exactly once")
    if lines.count(UPDATE) != 1:
        errors.append(f"Expected '{UPDATE}' exactly once")
    if errors:
        raise ValidationError(errors)
    n, u = lines.index(NEW), lines.index(UPDATE)
    if n >= u:
        raise ValidationError(["Unexpected header order: NEW must precede UPDATE"])
    if any(not x.strip() for x in lines[:n] + lines[u + 1 :]):
        raise ValidationError(["Unexpected prose before or after structured result"])
    sections = (lines[n + 1 : u], lines[u + 1 :])
    parsed: list[list[list[str]]] = []
    seen_rows: set[str] = set()
    seen_cn: set[str] = set()
    for name, section in zip(("NEW", "UPDATE"), sections):
        values = [line for line in section if line.strip()]
        if values == [EMPTY]:
            parsed.append([])
            continue
        if not values:
            raise ValidationError([f"{name}: missing list marker or rows"])
        if EMPTY in values:
            raise ValidationError([f"{name}: no-list marker cannot appear with rows"])
        result = []
        for line in values:
            if EMPTY in line or "|" in line or line.startswith(("- ", "* ", "```")):
                raise ValidationError(["Markdown contamination or misplaced no-list marker"])
            if "[" in line or "]" in line or "【" in line or "】" in line:
                raise ValidationError(["Citation marker or output noise detected"])
            fields = parse_tsv(line, 4)[0]
            cn, th, sex, note = fields
            if not cn.strip():
                raise ValidationError(["Empty CN"])
            if not th.strip():
                raise ValidationError(["Empty TH"])
            if not note.strip():
                raise ValidationError(["Empty NOTE"])
            if sex not in SEX_VALUES:
                raise ValidationError([f"Invalid SEX: {sex}"])
            if line in seen_rows:
                raise ValidationError(["Duplicate row"])
            if cn in seen_cn:
                raise ValidationError([f"Duplicate CN: {cn}"])
            seen_rows.add(line)
            seen_cn.add(cn)
            result.append(fields)
        parsed.append(result)
    return parsed[0], parsed[1]
