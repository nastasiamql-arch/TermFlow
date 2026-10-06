import pytest

from termflow.core.errors import ValidationError
from termflow.validators.step_a_validator import EMPTY, NEW, UPDATE, validate_step_a
from termflow.validators.step_b_validator import COPY_READY, validate_step_b


def a(new=None, update=None):
    return f"{NEW}\n{EMPTY if new is None else new}\n{UPDATE}\n{EMPTY if update is None else update}"


def test_step_a_valid_and_both_empty():
    assert validate_step_a(a("林雪\tหลินเสวี่ย\tหญิง\tศิษย์สำนัก"))[0][0][0] == "林雪"
    assert validate_step_a(a()) == ([], [])


def test_step_a_accepts_single_outer_code_block_required_by_prompt():
    raw = "```text\n" + a("林雪\tหลินเสวี่ย\tหญิง\tศิษย์สำนัก") + "\n```"
    new_rows, update_rows = validate_step_a(raw)
    assert new_rows[0][0] == "林雪"
    assert update_rows == []


def test_step_a_still_rejects_no_list_marker_mixed_with_rows():
    with pytest.raises(ValidationError, match="no-list marker cannot appear with rows"):
        validate_step_a(a(f"{EMPTY}\n林雪\tหลินเสวี่ย\tหญิง\tศิษย์สำนัก"))


@pytest.mark.parametrize(
    "raw",
    [
        f"林雪\tหลิน\tหญิง\tnote\n{UPDATE}\n{EMPTY}",
        f"{NEW}\n{EMPTY}",
        f"{UPDATE}\n{EMPTY}\n{NEW}\n{EMPTY}",
        a("CN\tTH\tชาย"),
        a("CN\tTH\tชาย\tn\textra"),
        a("CN\tTH\tother\tn"),
        a("CN\tTH\tชาย\tn\nCN\tTH\tชาย\tn"),
        a("\tTH\tชาย\tn"),
        a("CN\t\tชาย\tn"),
        a("CN\tTH\tชาย\t"),
        a("prose"),
        a("— ไม่มีรายการ —\tTH\tชาย\tn"),
        a("CN\tTH\tชาย\tn", "CN\tTH2\tชาย\tn"),
        "```text\n" + a("CN\tTH\tชาย\tn") + "\n```\nextra prose",
    ],
)
def test_step_a_invalid(raw):
    with pytest.raises((ValidationError, ValueError)):
        validate_step_a(raw)


def test_step_a_new_only_and_update_only():
    assert len(validate_step_a(a("CN\tTH\t-\tN"))[0]) == 1
    assert len(validate_step_a(a(update="CN2\tTH\tชาย\tN"))[1]) == 1


def test_step_b_contract():
    source = [[f"CN{i}", "TH", "NOTE"] for i in range(10)]
    valid = COPY_READY + "\n" + "\n".join("\t".join(r) for r in source)
    assert len(validate_step_b(valid, source)) == 10
    for rows in (source[:-1], source + [["CN10", "TH", "NOTE"]]):
        with pytest.raises(ValidationError):
            validate_step_b(COPY_READY + "\n" + "\n".join("\t".join(r) for r in rows), source)
    for bad in (["OTHER", "TH", "N"], ["CN0", "", "N"], ["CN0", "TH", ""]):
        with pytest.raises(ValidationError):
            validate_step_b(COPY_READY + "\n" + "\t".join(bad), source[:1])
    with pytest.raises(ValidationError):
        validate_step_b(COPY_READY + "\nCN0|TH|NOTE", source[:1])


def test_step_b_extracts_tsv_from_prompt_required_code_block():
    source = [["林雪", "หลินเสวี่ย", "ศิษย์สำนัก"]]
    raw = (
        "Analysis and summary may appear before the copy-ready result.\n"
        f"{COPY_READY}\n```text\n林雪\tหลินเสวี่ย\tศิษย์สำนัก\n```"
    )

    assert validate_step_b(raw, source) == source


def test_step_b_still_rejects_prose_or_extra_markdown_after_tsv_fence():
    source = [["林雪", "หลินเสวี่ย", "ศิษย์สำนัก"]]
    raw = f"{COPY_READY}\n```tsv\n林雪\tหลินเสวี่ย\tศิษย์สำนัก\n```\nextra prose"

    with pytest.raises(ValidationError, match="Markdown contamination"):
        validate_step_b(raw, source)
