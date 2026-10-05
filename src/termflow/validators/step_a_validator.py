from termflow.core.errors import ValidationError
from termflow.validators.common import parse_tsv

NEW = "=== คำศัพท์ใหม่ ==="
UPDATE = "=== คำศัพท์อัปเดต ==="
EMPTY = "— ไม่มีรายการ —"
SEX_VALUES = {"ชาย", "หญิง", "ยังไม่ยืนยัน", "-"}


def validate_step_a(raw: str) -> tuple[list[list[str]], list[list[str]]]:
    errors: list[str] = []
    lines = raw.splitlines()
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
