class TermFlowError(Exception):
    """Expected, user-displayable application error."""


class ValidationError(TermFlowError):
    def __init__(self, details: list[str]):
        self.details = details
        super().__init__("; ".join(details))
