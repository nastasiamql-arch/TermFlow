import pytest

from termflow.adapters.a_to_b_adapter import adapt_new_rows, restore_sex
from termflow.core.errors import ValidationError


def test_adapter_and_restore_multiple_rows():
    payload, adapted = adapt_new_rows([["林雪", "หลินเสวี่ย", "หญิง", "ศิษย์"], ["張三", "จางซาน", "ชาย", "ตัวละคร"]])
    assert payload == "林雪\tหลินเสวี่ย\tศิษย์\n張三\tจางซาน\tตัวละคร"
    assert [x.sex for x in adapted] == ["หญิง", "ชาย"]
    final = restore_sex([["張三", "จางซาน", "ขุนศึก"], ["林雪", "หลินเสวี่ย", "ศิษย์"]], adapted)
    assert final == [["張三", "จางซาน", "ชาย", "ขุนศึก"], ["林雪", "หลินเสวี่ย", "หญิง", "ศิษย์"]]


def test_duplicate_and_missing_cn_rejected():
    with pytest.raises(ValidationError):
        adapt_new_rows([["CN", "TH", "-", "n"], ["CN", "T2", "-", "n"]])
    _, adapted = adapt_new_rows([["CN", "TH", "-", "n"]])
    with pytest.raises(ValidationError):
        restore_sex([["OTHER", "TH", "N"]], adapted)
