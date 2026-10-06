"""Lossless format adapters. Never infer missing fields or vocabulary content."""

import csv
import json
import re

from termflow.core.errors import ValidationError


def unwrap(text: str) -> str:
    lines = text.splitlines()
    while lines and not lines[0].strip():
        lines.pop(0)
    while lines and not lines[-1].strip():
        lines.pop()
    if lines and re.fullmatch(r"```(?:text|tsv|csv|markdown|md|json)?\s*", lines[0], re.I):
        if len(lines) < 2 or lines[-1].strip() != "```":
            raise ValidationError(["กรอบโค้ดไม่ครบ · เปิดผลเดิมเพื่อแก้โดยไม่เรียก API"])
        lines = lines[1:-1]
    if any(line.strip().startswith("```") for line in lines):
        raise ValidationError(["กรอบโค้ดซ้อนหรือกำกวม · เปิดผลเดิมเพื่อแก้"])
    return "\n".join(lines)


def normalize_rows(text: str, columns: int) -> str:
    text = unwrap(text)
    expected = ["CN", "TH", "SEX", "NOTE"] if columns == 4 else ["CN", "TH", "NOTE"]
    if text.lstrip().startswith("["):
        try:
            rows = json.loads(text)
            if not isinstance(rows, list):
                raise ValueError("Expected JSON row array")
            parsed = []
            for row in rows:
                if isinstance(row, dict):
                    if set(row) not in (set(expected), {key.lower() for key in expected}):
                        raise ValueError("JSON row fields do not match required columns")
                    row = [row[key] if key in row else row[key.lower()] for key in expected]
                if not isinstance(row, list) or len(row) != columns:
                    raise ValueError(f"Expected {columns} JSON fields")
                if any(not isinstance(value, str) or any(char in value for char in "\t\r\n") for value in row):
                    raise ValueError("JSON fields must be single-line text")
                parsed.append("\t".join(row))
            return "\n".join(parsed)
        except (ValueError, TypeError, KeyError) as exc:
            raise ValidationError([str(exc)]) from exc
    lines = [line for line in text.splitlines() if line.strip()]
    output = []
    header_removed = False
    for line in lines:
        if "\t" in line:
            fields = line.split("\t")
        elif "|" in line:
            cells = line.strip()
            if cells.startswith("|") and cells.endswith("|"):
                cells = cells[1:-1]
            fields = [cell.strip() for cell in cells.split("|")]
        elif "," in line:
            try:
                fields = next(csv.reader([line], strict=True))
            except csv.Error as exc:
                raise ValidationError([str(exc)]) from exc
        else:
            output.append(line)
            continue
        if len(fields) != columns:
            raise ValidationError([f"Expected {columns} columns; Received {len(fields)} · แก้ผลเดิมได้โดยไม่เรียก API"])
        if not output and not header_removed and len(lines) > 1 and [field.strip().upper() for field in fields] == expected:
            header_removed = True
            continue
        if not output and header_removed and all(re.fullmatch(r":?-{3,}:?", field.strip()) for field in fields):
            continue
        if any("\t" in value or "\n" in value or "\r" in value for value in fields):
            raise ValidationError(["Ambiguous delimiters inside field"])
        output.append("\t".join(fields))
    return "\n".join(output)


def normalize_search(raw: str) -> str:
    from termflow.validators.step_a_validator import NEW, UPDATE

    text = raw.strip("\r\n ")
    # A single outer fence or one fence per section; headers remain mandatory.
    if text.startswith("```"):
        text = unwrap(text)
    if text.lstrip().startswith("{"):
        try:
            sections = json.loads(text)
            if set(sections) != {"new", "update"}:
                raise ValueError("JSON search must contain new and update arrays")
            new = normalize_rows(json.dumps(sections["new"], ensure_ascii=False), 4)
            update = normalize_rows(json.dumps(sections["update"], ensure_ascii=False), 4)
            return NEW + "\n" + (new or "— ไม่มีรายการ —") + "\n" + UPDATE + "\n" + (update or "— ไม่มีรายการ —")
        except (ValueError, TypeError) as exc:
            raise ValidationError([str(exc)]) from exc
    lines = text.splitlines()
    for index, line in enumerate(lines):
        candidate = re.sub(r"^#{1,6}\s+", "", line.strip())
        if candidate in {NEW, UPDATE}:
            lines[index] = candidate
    if lines.count(NEW) != 1 or lines.count(UPDATE) != 1:
        return text
    n, u = lines.index(NEW), lines.index(UPDATE)
    if n != 0 or n >= u:
        return text
    return NEW + "\n" + normalize_rows("\n".join(lines[n + 1:u]), 4) + "\n" + UPDATE + "\n" + normalize_rows("\n".join(lines[u + 1:]), 4)
