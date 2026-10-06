from datetime import datetime, timezone
from hashlib import sha256

from termflow.adapters.a_to_b_adapter import adapt_new_rows, restore_sex
from termflow.core.search_export import format_step_a_result
from termflow.core.state_machine import WorkflowState
from termflow.validators.step_a_validator import validate_step_a
from termflow.validators.step_b_validator import validate_step_b


class Workflow:
    """Application-owned orchestration; providers only return text."""

    def __init__(self):
        self.state = WorkflowState()
        self.source = ""
        self.vocab = ""
        self.search_raw = ""
        self.new_rows: list[list[str]] = []
        self.update_rows: list[list[str]] = []
        self.adapted = []
        self.final_rows: list[list[str]] = []
        self.excluded_rows: list[dict] = []
        self.pending_final: list[list[str]] = []
        self.exclusions_confirmed = False
        self.history: list[dict] = []

    def accept_search(self, raw: str) -> tuple[list[list[str]], list[list[str]]]:
        self.state.transition(self.state.current.__class__.SEARCH_VALIDATING)
        try:
            new, update = validate_step_a(raw)
        except Exception:
            self.state.transition(self.state.current.__class__.SEARCH_FAILED)
            raise
        self.search_raw, self.new_rows, self.update_rows = raw, new, update
        self.state.transition(self.state.current.__class__.SEARCH_COMPLETE)
        self.state.transition(self.state.current.__class__.USER_REVIEW)
        return new, update

    def prepare_polish(self, selected: list[list[str]]) -> str:
        b_input, self.adapted = adapt_new_rows(selected)
        self.excluded_rows = []
        self.pending_final = []
        self.exclusions_confirmed = False
        if self.state.current != self.state.current.__class__.POLISH_READY:
            self.state.transition(self.state.current.__class__.POLISH_READY)
        return b_input

    def begin_search(self) -> None:
        states = self.state.current.__class__
        if self.state.current == states.FINAL_READY:
            self.state.transition(states.USER_REVIEW)
        elif self.state.current == states.POLISH_FAILED:
            self.state.transition(states.POLISH_READY)
        if self.state.current == states.POLISH_READY:
            self.state.transition(states.USER_REVIEW)
        if self.state.current in {self.state.current.__class__.IDLE, self.state.current.__class__.SOURCE_LOADED}:
            self.state.transition(self.state.current.__class__.READY_FOR_SEARCH)
        self.state.transition(self.state.current.__class__.SEARCH_RUNNING)

    def begin_polish(self) -> None:
        self.state.transition(self.state.current.__class__.POLISH_RUNNING)

    def accept_polish(self, raw: str, b_input: str, *, allow_removals: bool = False) -> list[list[str]]:
        self.state.transition(self.state.current.__class__.POLISH_VALIDATING)
        self.excluded_rows = []
        self.pending_final = []
        self.exclusions_confirmed = False
        try:
            rows = validate_step_b(raw, [line.split("\t") for line in b_input.splitlines()], allow_removals=allow_removals)
            kept = {row[0] for row in rows}
            included = [row for row in self.adapted if row.cn in kept]
            self.excluded_rows = []
            for row in self.adapted:
                if row.cn not in kept:
                    cn, th, note = row.b_input.split("\t")
                    self.excluded_rows.append({"row_id": row.row_id, "cn": cn, "th": th, "sex": row.sex, "note": note})
            final = restore_sex(rows, included)
        except Exception:
            self.state.transition(self.state.current.__class__.POLISH_FAILED)
            raise
        if len(final) + len(self.excluded_rows) != len(self.adapted):
            self.state.transition(self.state.current.__class__.POLISH_FAILED)
            raise ValueError("Final result count does not match selected STEP A rows")
        self.state.transition(self.state.current.__class__.POLISH_COMPLETE)
        self.pending_final = final
        if not self.excluded_rows:
            self.confirm_polish_exclusions()
        return final

    def confirm_polish_exclusions(self) -> None:
        self.state.transition(self.state.current.__class__.FINAL_READY)
        self.final_rows = self.pending_final
        self.exclusions_confirmed = bool(self.excluded_rows)

    def reject_polish_exclusions(self) -> None:
        self.state.transition(self.state.current.__class__.POLISH_FAILED)
        self.pending_final = []
        self.exclusions_confirmed = False

    def restore_final_snapshot(self, rows: list[list[str]]) -> None:
        if any(not isinstance(row, list) or len(row) != 4 or any(not isinstance(value, str) for value in row) for row in rows):
            raise ValueError("History result must contain four text columns")
        validate_step_a(format_step_a_result(rows, []))
        self.state.transition(self.state.current.__class__.FINAL_READY)
        self.final_rows = rows


def snapshot(
    prompt_id: str,
    prompt_name: str,
    prompt_version: str,
    prompt: str,
    provider: str,
    model: str,
    input_text: str,
    raw: str,
    parsed,
    valid: bool,
) -> dict:
    return {
        "prompt_id": prompt_id,
        "prompt_name": prompt_name,
        "prompt_version": prompt_version,
        "prompt_text": prompt,
        "prompt_sha256": sha256(prompt.encode()).hexdigest(),
        "provider": provider,
        "model": model,
        "time": datetime.now(timezone.utc).isoformat(),
        "input_sha256": sha256(input_text.encode()).hexdigest(),
        "raw_response": raw,
        "parsed_result": parsed,
        "validation_valid": valid,
    }
