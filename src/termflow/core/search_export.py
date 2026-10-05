from termflow.validators.step_a_validator import EMPTY, NEW, UPDATE


def format_step_a_result(new_rows: list[list[str]], update_rows: list[list[str]]) -> str:
    """Format validated combined rows in the exact STEP A two-section form."""
    new = "\n".join("\t".join(row) for row in new_rows) or EMPTY
    updates = "\n".join("\t".join(row) for row in update_rows) or EMPTY
    return f"{NEW}\n{new}\n\n{UPDATE}\n{updates}\n"
