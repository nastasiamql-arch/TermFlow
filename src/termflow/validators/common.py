from pydantic import BaseModel, ConfigDict, Field


class GlossaryRow(BaseModel):
    model_config = ConfigDict(frozen=False)
    cn: str = Field(min_length=1)
    th: str = Field(min_length=1)
    sex: str = Field(min_length=1)
    note: str = Field(min_length=1)
    row_id: str = ""


def parse_tsv(text: str, columns: int) -> list[list[str]]:
    rows = []
    for line_no, line in enumerate(text.splitlines(), 1):
        if not line.strip():
            continue
        fields = line.split("\t")
        if len(fields) != columns:
            raise ValueError(f"Line {line_no}: Expected {columns} columns; Received {len(fields)}")
        rows.append(fields)
    return rows
