from datetime import datetime, timezone
from hashlib import sha256

from termflow.adapters.a_to_b_adapter import adapt_new_rows, restore_sex
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

    def accept_polish(self, raw: str, b_input: str) -> list[list[str]]:
        self.state.transition(self.state.current.__class__.POLISH_VALIDATING)
        try:
            rows = validate_step_b(raw, [line.split("\t") for line in b_input.splitlines()])
            final = restore_sex(rows, self.adapted)
        except Exception:
            self.state.transition(self.state.current.__class__.POLISH_FAILED)
            raise
        if len(final) != len(self.adapted):
            self.state.transition(self.state.current.__class__.POLISH_FAILED)
            raise ValueError("Final result count does not match selected STEP A rows")
        self.final_rows = final
        self.state.transition(self.state.current.__class__.POLISH_COMPLETE)
        self.state.transition(self.state.current.__class__.FINAL_READY)
        return final


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
