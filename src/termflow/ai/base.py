from abc import ABC, abstractmethod
from threading import Event

from pydantic import BaseModel


class GenerateRequest(BaseModel):
    prompt: str
    source: str = ""
    vocab: str = ""
    user_input: str = ""
    validation_step: str = ""
    expected_rows: list[list[str]] = []
    reuse_result: bool = True


class AIProvider(ABC):
    def __init__(self, api_key: str, model: str, timeout: int = 90, base_url: str = "", retries: int = 0):
        self.api_key, self.model, self.timeout, self.base_url = api_key, model, timeout, base_url
        self.retries = retries
        self.cancelled = Event()
        self._active_client = None

    @abstractmethod
    def generate(self, request: GenerateRequest) -> str: ...

    @abstractmethod
    def test_connection(self) -> bool: ...

    def list_models(self) -> list[str]:
        return []

    def cancel(self) -> None:
        self.cancelled.set()
        if self._active_client is not None:
            self._active_client.close()

    def check_cancelled(self) -> None:
        if self.cancelled.is_set():
            raise InterruptedError("Request cancelled")
