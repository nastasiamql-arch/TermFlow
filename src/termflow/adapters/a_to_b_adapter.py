from dataclasses import dataclass
from uuid import uuid4

from termflow.core.errors import ValidationError


@dataclass(frozen=True)
class AdaptedRow:
    row_id: str
    cn: str
    sex: str
    b_input: str


def adapt_new_rows(rows: list[list[str]]) -> tuple[str, list[AdaptedRow]]:
    result, seen = [], set()
    for cn, th, sex, note in rows:
        if cn in seen:
            raise ValidationError([f"Duplicate CN: {cn}"])
        seen.add(cn)
        result.append(AdaptedRow(str(uuid4()), cn, sex, "\t".join((cn, th, note))))
    return "\n".join(x.b_input for x in result), result


def restore_sex(polished: list[list[str]], adapted: list[AdaptedRow]) -> list[list[str]]:
    if len(polished) != len(adapted):
        raise ValidationError(["Final row count does not match selected STEP A rows"])
    sex_by_cn = {r.cn: r.sex for r in adapted}
    if len(sex_by_cn) != len(adapted):
        raise ValidationError(["Duplicate CN in selected rows"])
    final = []
    for cn, th, note in polished:
        if cn not in sex_by_cn:
            raise ValidationError([f"Unknown CN: {cn}"])
        final.append([cn, th, sex_by_cn[cn], note])
    if set(x[0] for x in final) != set(sex_by_cn):
        raise ValidationError(["Missing CN"])
    return final
