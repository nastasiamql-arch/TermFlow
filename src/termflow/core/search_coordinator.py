from concurrent.futures import ThreadPoolExecutor, as_completed
from threading import Event, Lock
from typing import Callable

from termflow.ai.base import GenerateRequest
from termflow.ai.service import ProviderConfig, create_provider
from termflow.core.search_batch import ChunkRun, ChunkStatus, SearchBatch

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
            request = GenerateRequest(
                prompt=self.prompt,
                source=run.chunk.text,
                vocab=self.vocab,
                user_input=(
                    "Return the requested result only. Do not write or modify files. "
                    f"This is SOURCE part {run.chunk.index} of 10. Apply the exact system Prompt to every line of this part."
                ),
            )
            raw = provider.generate(request)
            if self.cancelled.is_set():
                return
            self.batch.mark_validating(run.chunk.index)
            self._notify(run, "กำลังตรวจรูปแบบผลลัพธ์")
            accepted = self.batch.accept_response(run.chunk.index, raw)
            self._notify(run, "" if accepted else run.error)
        except Exception as exc:
            if not self.cancelled.is_set():
                self.batch.fail_chunk(run.chunk.index, str(exc))
                self._notify(run, run.error)
        finally:
            with self._providers_lock:
                self._providers.pop(run.chunk.index, None)

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
