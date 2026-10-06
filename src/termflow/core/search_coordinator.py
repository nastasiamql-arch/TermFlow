from concurrent.futures import ThreadPoolExecutor, as_completed
from threading import Event, Lock
from typing import Callable

import httpx

from termflow.ai.base import GenerateRequest
from termflow.ai.service import ProviderConfig, create_provider
from termflow.core.search_batch import ChunkRun, ChunkStatus, SearchBatch
from termflow.validators.step_a_validator import validate_step_a

ProgressCallback = Callable[[int, str, str, int, int], None]


class SearchCoordinator:
    """Run every non-empty SOURCE chunk in parallel using independent providers."""

    def __init__(
        self,
        batch: SearchBatch,
        *,
        prompt: str,
        vocab: str,
        config: ProviderConfig,
        api_key: str,
        on_progress: ProgressCallback | None = None,
        provider_factory=create_provider,
    ):
        self.batch = batch
        self.prompt = prompt
        self.vocab = vocab
        self.config = config
        self.api_key = api_key
        self.on_progress = on_progress or (lambda *_args: None)
        self.provider_factory = provider_factory
        self.cancelled = Event()
        self._providers = {}
        self._providers_lock = Lock()

    def cancel(self) -> None:
        self.cancelled.set()
        with self._providers_lock:
            providers = list(self._providers.values())
        for provider in providers:
            provider.cancel()

    def _notify(self, run: ChunkRun, message: str = "") -> None:
        self.on_progress(
            run.chunk.index,
            run.status.value,
            message or run.error,
            len(run.new_rows),
            len(run.update_rows),
        )

    def _run_chunk(self, run: ChunkRun) -> None:
        if self.cancelled.is_set():
            return
        self.batch.mark_running(run.chunk.index)
        self._notify(run)
        try:
            provider = self.provider_factory(self.config, self.api_key)
            with self._providers_lock:
                self._providers[run.chunk.index] = provider
            try:
                raw = self._generate_part(provider, run, run.chunk.text, depth=0, suffix="")
                if self.cancelled.is_set():
                    return
                self.batch.mark_validating(run.chunk.index)
                self._notify(run, "กำลังตรวจรูปแบบผลลัพธ์")
                accepted = self.batch.accept_response(run.chunk.index, raw)
            except _SplitCompleted as split_result:
                if self.cancelled.is_set():
                    return
                self.batch.mark_validating(run.chunk.index)
                self._notify(run, "ตรวจผลส่วนย่อย")
                accepted = self.batch.accept_split_responses(run.chunk.index, split_result.responses)
            self._notify(run, "" if accepted else run.error)
        except Exception as exc:
            if not self.cancelled.is_set():
                self.batch.fail_chunk(run.chunk.index, str(exc))
                self._notify(run, run.error)
        finally:
            with self._providers_lock:
                self._providers.pop(run.chunk.index, None)

    def _generate_part(self, provider, run: ChunkRun, source: str, *, depth: int, suffix: str) -> str:
        if self.cancelled.is_set():
            raise InterruptedError("Request cancelled")
        request = GenerateRequest(
            prompt=self.prompt,
            source=source,
            vocab=self.vocab,
            user_input=(
                "Return the requested result only. Do not write or modify files. "
                f"This is SOURCE part {run.chunk.index} of {len(self.batch.runs)}. "
                "Apply the exact system Prompt to every line of this part."
                f"{suffix}"
            ),
        )
        try:
            raw = provider.generate(request)
            validate_step_a(raw)
            return raw
        except httpx.ReadTimeout as exc:
            if depth >= 2:
                raise
            pieces = self._split_source(source)
            run.split_depth = max(run.split_depth, depth + 1)
            self._notify(run, f"หมดเวลารอ · แบ่งเฉพาะช่วงนี้เป็น {len(pieces)} ส่วนย่อย")
            responses: list[str] = []
            for sub_index, piece in enumerate(pieces, 1):
                if self.cancelled.is_set():
                    raise InterruptedError("Request cancelled")
                try:
                    responses.append(
                        self._generate_part(
                            provider,
                            run,
                            piece,
                            depth=depth + 1,
                            suffix=(
                                f" This is subpart {sub_index} of {len(pieces)} for SOURCE part "
                                f"{run.chunk.index} of {len(self.batch.runs)}."
                            ),
                        )
                    )
                except _SplitCompleted as nested:
                    responses.extend(nested.responses)
            raise _SplitCompleted(responses) from exc

    @staticmethod
    def _split_source(source: str) -> tuple[str, str]:
        """Split at a nearby line boundary without dropping or duplicating text."""
        midpoint = len(source) // 2
        boundaries = [index + 1 for index, char in enumerate(source) if char == "\n"]
        boundary = min(boundaries, key=lambda item: abs(item - midpoint)) if boundaries else midpoint
        if boundary <= 0 or boundary >= len(source):
            boundary = midpoint
        return source[:boundary], source[boundary:]

    def run(self) -> SearchBatch:
        for run in self.batch.runs:
            if run.status == ChunkStatus.COMPLETE and not run.raw_response:
                self._notify(run, "ไม่มีข้อความในช่วงนี้ · ข้ามการเรียก API")
        pending = [
            run
            for run in self.batch.runs
            if run.status == ChunkStatus.PENDING
            and run.chunk.core_start != run.chunk.core_end
            and run.chunk.text.strip()
        ]
        if pending and not self.cancelled.is_set():
            with ThreadPoolExecutor(max_workers=min(10, len(pending)), thread_name_prefix="termflow-search") as pool:
                futures = [pool.submit(self._run_chunk, run) for run in pending]
                for future in as_completed(futures):
                    future.result()
        if self.cancelled.is_set():
            self.batch.cancel_pending()
            for run in self.batch.runs:
                if run.status == ChunkStatus.CANCELLED:
                    self._notify(run, "Cancelled")
        return self.batch


class _SplitCompleted(Exception):
    def __init__(self, responses: list[str]):
        self.responses = responses
