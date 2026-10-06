import json
import os

import pytest

from termflow.core.errors import ValidationError
from termflow.core.search_batch import ChunkStatus, SearchBatch
from termflow.core.search_chunks import split_source
from termflow.validators.step_a_validator import EMPTY, NEW, UPDATE, validate_step_a
from termflow.validators.step_b_validator import COPY_READY, validate_step_b

A_ROW = ["林雪", "หลินเสวี่ย", "หญิง", "ศิษย์สำนัก"]
B_ROW = [A_ROW[0], A_ROW[1], A_ROW[3]]


@pytest.mark.parametrize("body", [
    "\t".join(A_ROW),
    " | ".join(A_ROW),
    "| CN | TH | SEX | NOTE |\n|---|---|---|---|\n| " + " | ".join(A_ROW) + " |",
    ",".join(A_ROW),
    json.dumps([dict(zip(["CN", "TH", "SEX", "NOTE"], A_ROW))]),
])
@pytest.mark.parametrize("fences", [False, True])
def test_search_common_formats(body, fences):
    if fences:
        body = "```tsv\n" + body + "\n```"
    raw = f"{NEW}\n{body}\n{UPDATE}\n{EMPTY}"
    assert validate_step_a(raw, flexible=True) == ([A_ROW], [])


def test_search_json_and_whole_fence():
    raw = json.dumps({"new": [A_ROW], "update": []})
    assert validate_step_a("\n```json\n" + raw + "\n```\n", flexible=True) == ([A_ROW], [])
    raw = f"```tsv\n{NEW}\n" + "\t".join(A_ROW) + f"\n{UPDATE}\n{EMPTY}\n```"
    assert validate_step_a(raw, flexible=True) == ([A_ROW], [])


@pytest.mark.parametrize("body", [
    "\t".join(B_ROW), " | ".join(B_ROW), ",".join(B_ROW),
    "| CN | TH | NOTE |\n|:---|---|---:|\n| " + " | ".join(B_ROW) + " |",
    json.dumps([B_ROW]),
])
def test_polish_common_formats(body):
    raw = "คำอธิบาย\n" + COPY_READY + "\n```text\n" + body + "\n```\nสรุป"
    assert validate_step_b(raw, [B_ROW], flexible=True) == [B_ROW]


@pytest.mark.parametrize("body", [
    "林雪 | หลินเสวี่ย | หญิง | ",
    "林雪 | หลินเสวี่ย | หญิง | NOTE | extra",
    "林雪 | หลินเสวี่ย | หญิง | NOTE\n林雪 | หลินเสวี่ย | หญิง | NOTE",
    "```tsv\n林雪\tหลินเสวี่ย\tหญิง\tNOTE", "คำอธิบายก่อนผล",
])
def test_formats_never_invent_or_drop_fields(body):
    with pytest.raises((ValidationError, ValueError)):
        validate_step_a(f"{NEW}\n{body}\n{UPDATE}\n{EMPTY}", flexible=True)


def test_batch_keeps_raw_failure_then_accepts_local_correction():
    batch = SearchBatch(split_source("นิยาย", 1))
    raw = f"{NEW}\n林雪\tหลินเสวี่ย\tหญิง\t\n{UPDATE}\n{EMPTY}"
    assert not batch.accept_response(1, raw)
    assert batch.runs[0].status == ChunkStatus.FAILED
    batch.retry_chunk(1)
    assert batch.accept_response(1, raw.replace("หญิง\t\n", "หญิง\tศิษย์สำนัก\n"))
    assert batch.runs[0].attempts[0]["raw_response"] == raw


def test_response_editor_requires_valid_content_before_accepting():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication, QDialog

    from termflow.ui.response_editor import ResponseEditor

    app = QApplication.instance() or QApplication([])
    dialog = ResponseEditor("bad", lambda raw: validate_step_a(raw, flexible=True))
    dialog.check()
    assert dialog.result() != QDialog.Accepted
    assert dialog.error.text()
    dialog.editor.setPlainText(f"{NEW}\n{EMPTY}\n{UPDATE}\n{EMPTY}")
    dialog.check()
    assert dialog.result() == QDialog.Accepted
    dialog.close()
    assert app is not None
