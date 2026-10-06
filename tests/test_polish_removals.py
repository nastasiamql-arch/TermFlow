import pytest
from PySide6.QtWidgets import QApplication, QDialog

from termflow.core.errors import ValidationError
from termflow.core.state_machine import State
from termflow.core.workflow import Workflow
from termflow.ui.polish_review import PolishRemovalReview
from termflow.validators.step_b_validator import COPY_READY, validate_step_b


def prepared_workflow():
    workflow = Workflow()
    workflow.begin_search()
    workflow.accept_search(
        "=== คำศัพท์ใหม่ ===\nCN1\tTH1\tหญิง\tNOTE1\nCN2\tTH2\tชาย\tNOTE2\n"
        "CN3\tTH3\tยังไม่ยืนยัน\tNOTE3\n=== คำศัพท์อัปเดต ===\n— ไม่มีรายการ —"
    )
    payload = workflow.prepare_polish(workflow.new_rows)
    workflow.begin_polish()
    return workflow, payload


def test_missing_row_requires_explicit_confirmation_and_keeps_sex_by_cn():
    workflow, payload = prepared_workflow()
    raw = f"ตัด CN2 เพราะซ้ำ VOCAB\n{COPY_READY}\n```tsv\nCN3\tTH3\tNOTE3\nCN1\tTH1\tNOTE1\n```"
    final = workflow.accept_polish(raw, payload, allow_removals=True)
    assert workflow.state.current == State.POLISH_COMPLETE
    assert workflow.final_rows == []
    assert not workflow.exclusions_confirmed
    assert [row[2] for row in final] == ["ยังไม่ยืนยัน", "หญิง"]
    removed = workflow.excluded_rows
    assert len(removed) == 1 and removed[0]["cn"] == "CN2"
    assert removed[0]["sex"] == "ชาย"
    assert removed[0]["row_id"] == next(row.row_id for row in workflow.adapted if row.cn == "CN2")
    assert len(final) + len(removed) == 3
    workflow.confirm_polish_exclusions()
    assert workflow.state.current == State.FINAL_READY
    assert workflow.final_rows == final
    assert workflow.exclusions_confirmed


def test_rejecting_removals_never_produces_final_result():
    workflow, payload = prepared_workflow()
    workflow.accept_polish(f"{COPY_READY}\nCN1\tTH1\tNOTE1", payload, allow_removals=True)
    workflow.reject_polish_exclusions()
    assert workflow.state.current == State.POLISH_FAILED
    assert not workflow.final_rows
    assert not workflow.pending_final
    assert not workflow.exclusions_confirmed


def test_empty_final_tsv_requires_confirmation_of_every_input_row():
    workflow, payload = prepared_workflow()
    final = workflow.accept_polish(f"{COPY_READY}\n```tsv\n```", payload, allow_removals=True)
    assert final == []
    assert len(workflow.excluded_rows) == 3
    assert workflow.state.current == State.POLISH_COMPLETE
    workflow.confirm_polish_exclusions()
    assert workflow.state.current == State.FINAL_READY


@pytest.mark.parametrize("tsv", ["OTHER\tTH\tNOTE", "CN1\tTH\tNOTE\nCN1\tTH\tNOTE", "CN1\t\tNOTE", "CN1\tTH\t"])
def test_removal_mode_still_rejects_unknown_duplicate_or_empty_fields(tsv):
    with pytest.raises(ValidationError):
        validate_step_b(f"{COPY_READY}\n{tsv}", [["CN1", "TH", "NOTE"], ["CN2", "TH", "NOTE"]], allow_removals=True)


def test_review_dialog_cannot_accept_without_checking_approval():
    _app = QApplication.instance() or QApplication([])
    dialog = PolishRemovalReview([{"cn": "CN", "th": "TH", "sex": "-", "note": "NOTE"}], "ตัด CN เพราะซ้ำ", 2)
    assert not dialog.confirm.isEnabled()
    dialog.accept()
    assert dialog.result() != QDialog.Accepted
    dialog.approval.setChecked(True)
    assert dialog.confirm.isEnabled()
    dialog.accept()
    assert dialog.result() == QDialog.Accepted


def test_valid_final_history_restores_a_copyable_state():
    workflow = Workflow()
    workflow.restore_final_snapshot([["CN", "TH", "หญิง", "NOTE"]])
    assert workflow.state.current == State.FINAL_READY
    assert workflow.final_rows == [["CN", "TH", "หญิง", "NOTE"]]
