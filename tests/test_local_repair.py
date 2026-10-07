from termflow.core.local_repair import repair_formatting
from termflow.core.errors import ValidationError
from termflow.validators.step_a_validator import NEW, UPDATE, validate_step_a
from termflow.validators.step_b_validator import COPY_READY, validate_step_b


def test_local_repair_normalizes_only_deterministic_headings_and_whitespace():
    raw = f"## {NEW}  \r\n— ไม่มีรายการ —\r\n  {UPDATE} \r\n— ไม่มีรายการ —\r\n\r\n"
    repaired = repair_formatting(raw, "A")
    assert repaired is not None
    assert validate_step_a(repaired) == ([], [])


def test_local_repair_preserves_semantic_invalidity():
    raw = f"# {COPY_READY}\nCN1\tTH\t"
    repaired = repair_formatting(raw, "B")
    assert repaired is not None
    try:
        validate_step_b(repaired, [["CN1", "TH", "NOTE"]])
        assert False, "missing NOTE must remain invalid"
    except ValidationError:
        pass
